"""Selenium 기반 네이버 블로그 글쓰기 엔진 (트로트 반상회 BloFit 전용).

검증된 New DSM BloFit 네이버 엔진을 그대로 이식하되, 기존 BloFit들과 충돌하지 않도록
크롬 디버그 포트 9701, 프로필 C:\\chrome_debug_trot 를 사용한다(동시 실행 안전).
런타임에 기존 illua_blofit 패키지에 의존하지 않는다(독립 업데이트 안전).
"""
from __future__ import annotations

import ctypes
import io
import json
import os
import random
import re
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pyautogui
import win32con
import win32gui
from PIL import Image
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .settings import IlluaSettings, credential_login_id, load_naver_password
from .config import DEBUGGER_ADDRESS as _TROT_DEBUGGER_ADDRESS


DEBUGGER_ADDRESS = _TROT_DEBUGGER_ADDRESS
MANUAL_LOGIN_WAIT_SECONDS = 120 * 60
MANUAL_LOGIN_POLL_SECONDS = 5
NAVER_HOME_URL = "https://www.naver.com/"
NAVER_LOGIN_URL = "https://nid.naver.com/nidlogin.login"
NAVER_WRITE_BASE = "https://blog.naver.com/{naver_id}?Redirect=Write"
TEXT_ONLY_MODE = False           # True: 사진 삽입 스킵, 텍스트만
IMAGES_FIRST_MODE = False        # True: 머리사진 먼저 → 본문 → 미용실사진 (Phase 1-A 우회)
INSERT_IMAGES_AFTER_TEXT = False # True: 본문 이후 토큰 치환 방식
SEGMENTED_IMAGE_MODE = True      # True: 원고 위치대로 텍스트↔이미지 분할 삽입
INSERT_SEPARATE_CTA = False      # True: CTA 별도 입력
DEFAULT_TEXT_COLOR = "#333333"
COLOR_TEXT_COLOR = "#0078cb"
POINT_TEXT_COLOR = "#ba0000"
HEADING_TEXT_COLOR = "#007433"
READABLE_TEXT_COLORS = (
    "#0078cb",  # deep blue
    "#007433",  # deep green
    "#ba0000",  # deep red
    "#006666",  # teal
    "#8a2be2",  # purple
    "#9a005d",  # wine
    "#0050a4",  # navy blue
    "#c45a00",  # burnt orange
    "#4b5f00",  # olive
    "#7a3e00",  # brown
)
HEADING_FONT_SIZE = "19"
DEFAULT_FONT_SIZE = "15"


def _build_write_url(naver_id: str) -> str:
    return NAVER_WRITE_BASE.format(naver_id=naver_id.strip())


def _is_debugger_running() -> bool:
    host, port = DEBUGGER_ADDRESS.split(":")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        return sock.connect_ex((host, int(port))) == 0


def inspect_debug_chrome_targets(timeout: float = 3.0) -> dict:
    """Return a lightweight CDP target snapshot without creating Selenium sessions."""
    info = {
        "debugger_address": DEBUGGER_ADDRESS,
        "version_ok": False,
        "target_count": 0,
        "page_count": 0,
        "write_tab_count": 0,
        "naver_home_count": 0,
        "closed_targets": [],
        "errors": [],
    }
    try:
        with urllib.request.urlopen(f"http://{DEBUGGER_ADDRESS}/json/version", timeout=timeout) as response:
            version = json.loads(response.read().decode("utf-8", errors="replace"))
        info["version_ok"] = True
        info["browser"] = version.get("Browser", "")
    except Exception as exc:
        info["errors"].append(f"version: {exc}")
        return info
    try:
        with urllib.request.urlopen(f"http://{DEBUGGER_ADDRESS}/json/list", timeout=timeout) as response:
            targets = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        info["errors"].append(f"list: {exc}")
        return info
    pages = [target for target in targets if target.get("type") == "page"]
    info["target_count"] = len(targets)
    info["page_count"] = len(pages)
    info["write_tab_count"] = sum(1 for target in pages if "Redirect=Write" in (target.get("url") or ""))
    info["naver_home_count"] = sum(1 for target in pages if (target.get("url") or "").rstrip("/") == NAVER_HOME_URL.rstrip("/"))
    return info


def cleanup_debug_chrome_for_selenium(timeout: float = 3.0) -> dict:
    """Close stale New DSM tabs that commonly make ChromeDriver attach hang.

    The cleanup is intentionally narrow: it only targets unsaved write tabs opened
    by Blofit tests, Naver logout tabs, about:blank pages, and duplicate Naver home
    tabs. It does not close public post/list tabs.
    """
    info = inspect_debug_chrome_targets(timeout=timeout)
    info["closed_targets"] = []
    if not info.get("version_ok"):
        return info
    try:
        with urllib.request.urlopen(f"http://{DEBUGGER_ADDRESS}/json/list", timeout=timeout) as response:
            targets = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        info["errors"].append(f"cleanup-list: {exc}")
        return info
    home_kept = False
    for target in targets:
        if target.get("type") != "page":
            continue
        target_id = target.get("id") or ""
        url = target.get("url") or ""
        title = target.get("title") or ""
        close_reason = ""
        if url == "about:blank":
            close_reason = "about_blank"
        elif "nidlogin.logout" in url:
            close_reason = "naver_logout"
        elif "Redirect=Write" in url:
            close_reason = "stale_write_tab"
        elif url.rstrip("/") == NAVER_HOME_URL.rstrip("/"):
            if home_kept:
                close_reason = "duplicate_naver_home"
            else:
                home_kept = True
        if not close_reason or not target_id:
            continue
        try:
            quoted_id = urllib.parse.quote(target_id, safe="")
            with urllib.request.urlopen(f"http://{DEBUGGER_ADDRESS}/json/close/{quoted_id}", timeout=timeout):
                pass
            info["closed_targets"].append({"id": target_id, "reason": close_reason, "title": title, "url": url})
        except Exception as exc:
            info["errors"].append(f"close {close_reason}: {exc}")
    refreshed = inspect_debug_chrome_targets(timeout=timeout)
    info["target_count_after"] = refreshed.get("target_count")
    info["page_count_after"] = refreshed.get("page_count")
    info["write_tab_count_after"] = refreshed.get("write_tab_count")
    info["naver_home_count_after"] = refreshed.get("naver_home_count")
    return info


class IlluaNaverEngine:
    """일루아 Blofit 전용 네이버 글쓰기 Selenium 엔진 (DSM NaverBlogEngineV3 포팅)."""

    def __init__(self, settings: IlluaSettings, log_callback=None) -> None:
        self.settings = settings
        self.driver = None
        self.log_callback = log_callback
        self._color_cursor = 0
        self._size_dirty = False  # 큰 폰트 사용 후 일반 텍스트에서 기본크기 재적용용
        self.wait_for_manual_challenge = True
        self.last_debug_preflight: dict = {}
        pyautogui.FAILSAFE = True

    def _log(self, msg: str) -> None:
        if self.log_callback:
            self.log_callback(msg)

    # ─── 연결 ──────────────────────────────────────────────────────────────

    def connect(self) -> tuple[bool, str]:
        if not _is_debugger_running():
            return False, f"Chrome 디버그 포트({DEBUGGER_ADDRESS})가 열려 있지 않습니다. 먼저 트로트 블로핏 로그인 크롬을 실행하세요."
        self.last_debug_preflight = inspect_debug_chrome_targets()
        options = Options()
        options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
        last_error = None
        for attempt in range(1, 3):
            try:
                self.driver = webdriver.Chrome(options=options)
                self.driver.set_page_load_timeout(15)
                self.driver.set_script_timeout(8)
                return True, "Chrome 연결 성공"
            except Exception as exc:
                last_error = exc
                self._log(f"ChromeDriver attach failed attempt {attempt}: {exc}")
                if attempt == 1:
                    cleanup = cleanup_debug_chrome_for_selenium()
                    self.last_debug_preflight["cleanup_after_failed_attach"] = cleanup
                    closed = len(cleanup.get("closed_targets") or [])
                    self._log(f"Chrome debug cleanup before retry: closed_targets={closed}")
                    time.sleep(3)
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        return False, f"Chrome 연결 실패: {last_error}"

    def _normalize_window(self) -> None:
        if not self.driver:
            return
        best_handle, best_score = None, -1
        for handle in self.driver.window_handles:
            try:
                self.driver.switch_to.window(handle)
                url = (self.driver.current_url or "").lower()
            except Exception:
                continue
            score = 3 if url.startswith(("http://", "https://")) else (2 if url == "about:blank" else 0)
            if score >= best_score:
                best_score, best_handle = score, handle
        if best_handle:
            self.driver.switch_to.window(best_handle)

    # ─── 크롬 창 포커스 (DSM과 동일) ────────────────────────────────────────

    def _bring_chrome_to_front(self) -> bool:
        if not self.driver:
            return False
        try:
            self.driver.maximize_window()
        except Exception:
            pass
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)
        except Exception:
            pass
        try:
            current_tab_title = (self.driver.title or "").strip()
        except Exception:
            current_tab_title = ""

        matches: list[tuple[int, str]] = []

        def _collect(hwnd, _):
            if not (win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd)):
                return
            if "Chrome_WidgetWin_1" not in win32gui.GetClassName(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            title_lower = title.lower()
            # Streamlit/BloFit UI 창은 제외
            if any(kw in title_lower for kw in ("blofit", "localhost:8536", "localhost:8501", "streamlit")):
                return
            matches.append((hwnd, title))

        win32gui.EnumWindows(_collect, None)
        if not matches:
            return False

        target_hwnd = None
        if current_tab_title:
            for hwnd, title in matches:
                if current_tab_title.lower() in title.lower() or title.lower() in current_tab_title.lower():
                    target_hwnd = hwnd
                    break
        if target_hwnd is None:
            for hwnd, title in matches:
                if any(kw in title.lower() for kw in ("naver", "blog", "네이버")):
                    target_hwnd = hwnd
                    break
        if target_hwnd is None:
            target_hwnd = matches[0][0]

        foreground_hwnd = win32gui.GetForegroundWindow()
        if foreground_hwnd:
            try:
                foreground_title = (win32gui.GetWindowText(foreground_hwnd) or "").lower()
                if any(kw in foreground_title for kw in ("blofit", "localhost:8536", "streamlit")):
                    win32gui.ShowWindow(foreground_hwnd, win32con.SW_MINIMIZE)
                    time.sleep(0.4)
            except Exception:
                pass

        for _ in range(4):
            try:
                if win32gui.IsIconic(target_hwnd):
                    win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                    time.sleep(0.4)
                win32gui.ShowWindow(target_hwnd, win32con.SW_MAXIMIZE)
                time.sleep(0.2)
                win32gui.ShowWindow(target_hwnd, win32con.SW_SHOW)
                win32gui.BringWindowToTop(target_hwnd)
                win32gui.SetForegroundWindow(target_hwnd)
                time.sleep(0.5)
                if win32gui.GetForegroundWindow() == target_hwnd:
                    return True
            except Exception:
                time.sleep(0.3)
        return False

    # ─── 에디터 DOM 확인 / 프레임 탐색 ────────────────────────────────────

    def _is_editor_dom_ready(self) -> bool:
        """현재 컨텍스트에 SmartEditor ONE 에디터가 '보이는(렌더된)' 상태로 준비됐는지 확인.
        DOM만 있고 안 보이는(초기화 전) 상태에선 False → 입력 시도 전 충분히 대기하게 한다."""
        js = """
function vis(el){ return !!el && el.offsetParent !== null && el.getClientRects().length > 0; }
const sels = [
  '.se-documentTitle [contenteditable="true"]',
  '.se-title-text [contenteditable="true"]',
  '.se-documentTitle .se-text-paragraph',
  '.se-component-content-editable[contenteditable="true"]'
];
for (const s of sels){ if (vis(document.querySelector(s))) return true; }
// 폴백: 보이는 contenteditable가 2개 이상이면(제목+본문) 준비된 것으로 간주
const ce = Array.from(document.querySelectorAll('[contenteditable="true"]')).filter(vis);
return ce.length >= 2;
"""
        try:
            return bool(self.driver.execute_script(js))
        except Exception:
            return False

    def _switch_to_editor_frame(self) -> None:
        """에디터 DOM이 있는 컨텍스트로 이동합니다. 이미 default에 있으면 그대로 둡니다."""
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        if self._is_editor_dom_ready():
            return  # default context에 에디터가 있음 (Smart Editor ONE 일반 모드)
        frame_candidates = [
            (By.ID, "mainFrame"),
            (By.ID, "editorFrame"),
            (By.ID, "se2_iframe"),
            (By.NAME, "mainFrame"),
        ]
        last_exc = None
        for locator in frame_candidates:
            try:
                WebDriverWait(self.driver, 5).until(EC.frame_to_be_available_and_switch_to_it(locator))
                if self._is_editor_dom_ready():
                    return
                self.driver.switch_to.default_content()
                last_exc = RuntimeError(f"frame {locator} found but editor DOM not ready")
            except Exception as exc:
                last_exc = exc
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
        # 모든 iframe 순회
        found_editor_frame = False
        try:
            self.driver.switch_to.default_content()
            frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            for frame in frames:
                try:
                    self.driver.switch_to.default_content()
                    self.driver.switch_to.frame(frame)
                    if self._is_editor_dom_ready():
                        found_editor_frame = True
                        return
                except Exception as exc:
                    last_exc = exc
                    continue
        finally:
            if not found_editor_frame:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
        if self._is_editor_dom_ready():
            return
        raise RuntimeError(f"에디터 프레임을 찾지 못했습니다: {last_exc}")

    def _ensure_editor_ready(self) -> bool:
        """에디터 DOM이 있는 컨텍스트로 이동해 유지. mainFrame iframe이 있으면 그 안에 에디터가
        있으므로 '먼저' 진입한다(default content의 placeholder에 잘못 입력되는 문제 방지).
        gootm10처럼 default에 에디터가 있는 블로그도 폴백으로 지원."""
        # 1순위: mainFrame iframe 내부 (trot_bansanghoe 등 — 에디터가 iframe 안)
        try:
            self.driver.switch_to.default_content()
            frames = self.driver.find_elements(By.ID, "mainFrame")
            if frames:
                try:
                    self.driver.switch_to.frame(frames[0])
                    if self._is_editor_dom_ready():
                        return True
                except Exception:
                    pass
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
        except Exception:
            pass
        # 2순위: default content (gootm10 등 — 에디터가 바깥에 바로)
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        if self._is_editor_dom_ready():
            return True
        # 3순위: 그 외 모든 frame 탐색
        try:
            self._switch_to_editor_frame()
            if self._is_editor_dom_ready():
                return True
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            return self._is_editor_dom_ready()
        except Exception:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
        return False

    def _run_in_contexts(self, callback):
        """default 컨텍스트와 frame 컨텍스트 모두에서 callback을 시도합니다."""
        results = []
        for context in ("default", "frame"):
            try:
                self.driver.switch_to.default_content()
                if context == "frame":
                    self._switch_to_editor_frame()
                results.append(callback())
            except Exception:
                continue
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        return results

    # ─── 팝업 처리 ─────────────────────────────────────────────────────────

    def _handle_popups(self) -> None:
        popup_kw = ["작성 중인 글", "이어서 작성하시겠습니까", "임시저장", "계속 작성", "새 글"]
        cancel_kw = ["취소", "새 글", "삭제", "닫기"]
        for context in ("default", "frame"):
            try:
                self.driver.switch_to.default_content()
                if context == "frame":
                    try:
                        self._switch_to_editor_frame()
                    except Exception:
                        continue
                clicked = self.driver.execute_script(
                    """
const popupKw=arguments[0], cancelKw=arguments[1];
const dialogs=Array.from(document.querySelectorAll('.se-popup-container,[role="dialog"]'));
for(const d of dialogs){
  const t=(d.innerText||'').trim();
  if(!t||!popupKw.some(k=>t.includes(k)))continue;
  const btns=Array.from(d.querySelectorAll('button'));
  const cancel=btns.find(b=>cancelKw.some(k=>(b.innerText||'').includes(k)));
  if(cancel){cancel.click();return true;}
}return false;
""",
                    popup_kw, cancel_kw,
                )
                if clicked:
                    time.sleep(1.2)
                    return
            except Exception:
                continue
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

    # ─── 로그인 확인/자동 로그인 ─────────────────────────────────────────────

    def _has_naver_session(self) -> bool:
        try:
            cookie_names = {c.get("name") for c in self.driver.get_cookies()}
            return {"NID_AUT", "NID_SES"}.issubset(cookie_names)
        except Exception:
            return False

    def _looks_like_login_blocked(self) -> bool:
        try:
            body = (self.driver.find_element(By.TAG_NAME, "body").text or "").lower()
        except Exception:
            return False
        blocked_keywords = [
            "보안문자",
            "자동입력",
            "캡차",
            "captcha",
            "비정상",
            "2단계",
            "인증",
            "보호조치",
        ]
        return any(keyword.lower() in body for keyword in blocked_keywords)

    def _type_into_login_field(self, selectors: list[str], value: str) -> bool:
        for selector in selectors:
            try:
                element = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                element.click()
                time.sleep(random.uniform(0.35, 0.6))
                existing = element.get_attribute("value") or ""
                self._log(f"로그인 입력칸 감지: selector={selector}, 기존값 길이={len(existing)}")
                if existing:
                    self._log("기존 로그인 입력값 삭제 시작")
                    ActionChains(self.driver).send_keys(Keys.END).perform()
                    time.sleep(random.uniform(0.15, 0.25))
                    for _ in range(len(existing) + 2):
                        ActionChains(self.driver).send_keys(Keys.BACKSPACE).perform()
                        time.sleep(random.uniform(0.06, 0.13))
                still_existing = element.get_attribute("value") or ""
                if still_existing:
                    self._log(f"Backspace 후 값이 남아 있어 전체 선택 삭제 재시도: 남은 길이={len(still_existing)}")
                    ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
                    time.sleep(random.uniform(0.15, 0.25))
                    ActionChains(self.driver).send_keys(Keys.BACKSPACE).perform()
                    time.sleep(random.uniform(0.2, 0.35))
                after_clear = element.get_attribute("value") or ""
                self._log(f"로그인 입력칸 삭제 완료: 남은값 길이={len(after_clear)}")
                for char in value:
                    ActionChains(self.driver).send_keys(char).perform()
                    time.sleep(random.uniform(0.09, 0.18))
                typed = element.get_attribute("value") or ""
                self._log(f"로그인 입력 완료: 입력 후 길이={len(typed)}")
                return True
            except Exception:
                continue
        return False

    def _click_login_submit(self) -> bool:
        for selector in ["#log\\.login", ".btn_login", "button[type='submit']", "input[type='submit']"]:
            try:
                button = WebDriverWait(self.driver, 4).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                button.click()
                self._log(f"로그인 버튼 클릭 완료: {selector}")
                return True
            except Exception:
                continue
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        self._log("로그인 버튼 대신 Enter 입력")
        return True

    def _submit_login_by_enter(self) -> bool:
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        self._log("저장된 로그인 입력값으로 Enter 제출")
        return True

    def _focus_login_id_and_enter(self) -> bool:
        if "nidlogin.login" not in self.driver.current_url:
            return False
        try:
            id_el = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#id, input[name='id']"))
            )
            id_el.click()
            time.sleep(random.uniform(0.25, 0.45))
            self._log("로그인 ID 입력칸 선택 후 Enter 제출")
            return self._submit_login_by_enter()
        except Exception as exc:
            self._log(f"로그인 ID 입력칸 Enter 제출 실패: {exc}")
            return False

    def _submit_prefilled_login_if_ready(self, login_id: str) -> bool:
        if "nidlogin.login" not in self.driver.current_url:
            return False
        try:
            id_el = WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#id, input[name='id']"))
            )
            pw_el = WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#pw, input[name='pw']"))
            )
            existing_id = (id_el.get_attribute("value") or "").strip()
            existing_pw = pw_el.get_attribute("value") or ""
            self._log(
                f"로그인 폼 기존 입력값 확인: id_len={len(existing_id)}, "
                f"pw_len={len(existing_pw)}, id_match={existing_id == login_id}"
            )
            if existing_id == login_id and existing_pw:
                self._log("ID/PW가 이미 입력되어 있어 재입력 없이 Enter로 로그인 제출")
                return self._submit_login_by_enter()
        except Exception as exc:
            self._log(f"기존 로그인 입력값 확인 건너뜀: {exc}")
        return False

    def _open_login_from_naver_home(self) -> tuple[bool, str]:
        self.driver.get(NAVER_HOME_URL)
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(0.8)
        self._log(f"네이버 메인 진입: {self.driver.current_url}")
        if self._has_naver_session():
            return True, "이미 로그인되어 있습니다."

        clicked = False
        selectors = [
            "a[href*='nidlogin.login']",
            "a[href*='nid.naver.com/nidlogin.login']",
            "a.MyView-module__link_login",
            "a[class*='link_login']",
        ]
        for selector in selectors:
            try:
                element = WebDriverWait(self.driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                element.click()
                clicked = True
                self._log(f"네이버 메인 로그인 버튼 클릭: {selector}")
                break
            except Exception:
                continue
        if not clicked:
            try:
                clicked = bool(
                    self.driver.execute_script(
                        """
const candidates = Array.from(document.querySelectorAll('a, button'));
const target = candidates.find((el) => {
  const text = (el.innerText || el.textContent || '').trim();
  const href = el.href || '';
  return href.includes('nidlogin.login') || text === '로그인' || text.includes('로그인');
});
if (target) { target.click(); return true; }
return false;
"""
                    )
                )
                if clicked:
                    self._log("네이버 메인 로그인 버튼 클릭: text/js fallback")
            except Exception as exc:
                self._log(f"네이버 메인 로그인 버튼 JS 탐색 실패: {exc}")
        if not clicked:
            return False, "네이버 메인 로그인 버튼을 찾지 못했습니다."

        WebDriverWait(self.driver, 10).until(lambda d: "nidlogin.login" in d.current_url or self._has_naver_session())
        time.sleep(0.8)
        if self._has_naver_session():
            return True, "이미 로그인되어 있습니다."
        if "nidlogin.login" in self.driver.current_url:
            return False, "로그인 페이지로 이동했습니다."
        return False, f"로그인 페이지 이동을 확인하지 못했습니다: {self.driver.current_url}"

    def _wait_for_login_result(self) -> tuple[bool, str]:
        time.sleep(1.2)
        if (
            not self._has_naver_session()
            and "nidlogin.login" in self.driver.current_url
            and not self._looks_like_login_blocked()
        ):
            ActionChains(self.driver).send_keys(Keys.ENTER).perform()
            self._log("로그인 제출 재시도: Enter")

        for _ in range(16):
            time.sleep(0.7)
            if self._has_naver_session():
                return True, "자동 로그인 성공"
            if self._looks_like_login_blocked():
                self._log(f"자동 로그인 차단 화면 감지: {self.driver.current_url}")
                if not self.wait_for_manual_challenge:
                    return False, "봇검사/추가 인증 화면이 감지되었습니다."
                return self._wait_for_manual_login_after_challenge()
        self._log(f"자동 로그인 세션 확인 실패: {self.driver.current_url}")
        return False, "자동 로그인 후 세션 쿠키를 확인하지 못했습니다."

    def _wait_for_manual_login_after_challenge(self) -> tuple[bool, str]:
        self._log("봇검사/추가 인증 감지. 텔레그램 알림 후 수동 인증을 기다립니다.")
        try:
            cardnews_root = Path(__file__).resolve().parents[2]
            if str(cardnews_root) not in sys.path:
                sys.path.insert(0, str(cardnews_root))
            from notify import send as send_blog_telegram

            send_blog_telegram(
                "⚠️ [도토리뉴스 블로그]\n"
                "네이버 로그인 수동 인증이 필요해요.\n"
                "전용 크롬에서 인증을 완료한 뒤 이 채팅에 '블로그'라고 보내주세요.\n"
                "대기 시간: 최대 10분"
            )
        except Exception as exc:
            self._log(f"수동 인증 텔레그램 알림 실패: {exc}")

        deadline = time.time() + MANUAL_LOGIN_WAIT_SECONDS
        next_log_at = time.time()
        while time.time() < deadline:
            try:
                if self._has_naver_session():
                    return True, "수동 인증 후 로그인 성공"
            except Exception:
                pass
            if time.time() >= next_log_at:
                remain = int(deadline - time.time())
                self._log(f"수동 인증 대기 중... 남은 시간 약 {max(0, remain)}초")
                next_log_at = time.time() + 30
            time.sleep(MANUAL_LOGIN_POLL_SECONDS)
        return False, "봇검사/추가 인증 화면이 감지되었고, 10분 안에 수동 인증이 완료되지 않았습니다."

    def _attempt_auto_login(self, force_input: bool = False) -> tuple[bool, str]:
        if not self.settings.auto_login_enabled:
            return False, "자동 로그인이 꺼져 있습니다."
        login_id = credential_login_id(self.settings)
        password = load_naver_password(login_id)
        if not login_id:
            return False, "자동 로그인 ID가 없습니다."

        self._log("자동 로그인 필요 여부 확인 중...")
        self._bring_chrome_to_front()
        try:
            if not force_input:
                try:
                    home_ok, home_msg = self._open_login_from_naver_home()
                    if home_ok:
                        self._log(f"네이버 메인 로그인 경로 결과: {home_msg}")
                        return True, "이미 로그인되어 있습니다."
                    self._log(f"네이버 메인 로그인 경로 결과: {home_msg}")
                    if "nidlogin.login" in self.driver.current_url:
                        if self._focus_login_id_and_enter():
                            ok, msg = self._wait_for_login_result()
                            if ok:
                                return ok, msg
                            self._log(f"ID칸 Enter 우선 제출 결과: {msg}")
                            if "봇검사" in msg or "추가 인증" in msg:
                                return False, msg
                        if self._submit_prefilled_login_if_ready(login_id):
                            return self._wait_for_login_result()
                except Exception as exc:
                    self._log(f"기존 세션 선확인 실패, 로그인 페이지 확인으로 진행: {exc}")

            if "nidlogin.login" not in self.driver.current_url:
                self.driver.get(NAVER_LOGIN_URL)
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(1.0)
            self._log(f"자동 로그인 페이지 진입: {self.driver.current_url}")
            if self._has_naver_session() and not force_input:
                self._log("로그인 페이지 진입 후 기존 세션 확인. 추가 입력 생략")
                return True, "이미 로그인되어 있습니다."

            if not force_input and self._submit_prefilled_login_if_ready(login_id):
                return self._wait_for_login_result()

            if not password:
                return False, "브라우저 저장 로그인값을 확인했지만 제출할 수 없었고, Windows Credential 비밀번호도 없습니다."

            if not self._type_into_login_field(["#id", "input[name='id']"], login_id):
                return False, "로그인 ID 입력칸을 찾지 못했습니다."
            self._log("자동 로그인 ID 입력 완료")
            if not self._type_into_login_field(["#pw", "input[name='pw']"], password):
                return False, "비밀번호 입력칸을 찾지 못했습니다."
            self._log("자동 로그인 비밀번호 입력 완료")

            self._click_login_submit()
            return self._wait_for_login_result()
        except Exception as exc:
            return False, f"자동 로그인 실패: {exc}"

    def _ensure_logged_in(self) -> tuple[bool, str]:
        try:
            self.driver.get(NAVER_HOME_URL)
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(1.0)
            if self._has_naver_session():
                return True, "로그인 세션 확인"
            return self._attempt_auto_login()
        except Exception as exc:
            return False, f"로그인 확인 실패: {exc}"

    # ─── 글쓰기 창 열기 ────────────────────────────────────────────────────

    def _make_page_visible(self) -> None:
        """페이지를 visibilityState='visible'로 만든다 — 네이버 SmartEditor는 페이지가 보일 때만
        입력칸(contenteditable)을 렌더한다. 백그라운드/비활성 탭에서도 동작하게 CDP로 탭 활성화."""
        try:
            self.driver.execute_cdp_cmd("Page.bringToFront", {})
        except Exception:
            pass

    def _open_editor(self) -> tuple[bool, str]:
        url = _build_write_url(self.settings.naver_id)
        for attempt in range(3):
            self._bring_chrome_to_front()
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            try:
                self.driver.get(url)
                time.sleep(2.0)
                self._make_page_visible()   # 탭 활성화(visibilityState=visible) → 에디터 렌더 유도
                self._bring_chrome_to_front()
                self._handle_popups()
                # 에디터가 '보이는' 상태로 준비될 때까지 대기 (최대 ~20초). 매번 bringToFront 재시도.
                for _ in range(25):
                    self._make_page_visible()
                    if self._ensure_editor_ready():
                        return True, f"attempt={attempt + 1}"
                    self._handle_popups()
                    time.sleep(0.8)
                if self._ensure_editor_ready():
                    return True, f"attempt={attempt + 1}"
            except Exception:
                time.sleep(1.0)
        return False, "글쓰기 창을 열지 못했습니다."

    def _open_editor_in_new_tab(self) -> tuple[bool, str]:
        """Open a fresh Smart Editor tab without navigating the current tab."""
        url = _build_write_url(self.settings.naver_id)
        for attempt in range(3):
            self._bring_chrome_to_front()
            try:
                self.driver.switch_to.new_window("tab")
            except Exception:
                try:
                    self.driver.execute_script("window.open('about:blank', '_blank');")
                    self.driver.switch_to.window(self.driver.window_handles[-1])
                except Exception:
                    time.sleep(1.0)
                    continue
            try:
                self.driver.get(url)
                time.sleep(2.0)
                self._bring_chrome_to_front()
                self._handle_popups()
                for _ in range(10):
                    if self._ensure_editor_ready():
                        return True, f"new_tab_attempt={attempt + 1}"
                    self._handle_popups()
                    time.sleep(0.8)
                if self._ensure_editor_ready():
                    return True, f"new_tab_attempt={attempt + 1}"
            except Exception:
                time.sleep(1.0)
        return False, "새 글쓰기 탭을 열지 못했습니다."

    # ─── 제목 입력 (default 컨텍스트 우선) ────────────────────────────────

    def _focus_title(self) -> bool:
        js = """
const selectors=[
  '.se-documentTitle [contenteditable="true"]',
  '.se-title-text [contenteditable="true"]',
  '.se-title-text',
  '[placeholder="제목"]',
  '[data-placeholder="제목"]'
];
for(const sel of selectors){
  const node=document.querySelector(sel);
  if(!node)continue;
  if(node.scrollIntoView)node.scrollIntoView({block:'center'});
  node.focus();node.click();return true;
}
const n=Array.from(document.querySelectorAll('[contenteditable="true"]')).find(e=>e.closest('.se-documentTitle,.se-title-text'));
if(n){n.focus();n.click();return true;}
return false;
"""
        for _ in range(3):
            try:
                if self.driver.execute_script(js):
                    time.sleep(0.3)
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        return False

    def _set_title_via_js(self, title: str) -> bool:
        return False

    def _find_title_element(self):
        # Prefer visible paragraph/module boxes over zero-width __se-node spans.
        # Recent Smart Editor exposes a hidden global contenteditable div for
        # clipboard handling, so only title-scoped visible elements are valid.
        for by, value in (
            (By.CSS_SELECTOR, ".se-documentTitle .se-text-paragraph"),
            (By.CSS_SELECTOR, ".se-title-text .se-text-paragraph"),
            (By.CSS_SELECTOR, ".se-documentTitle .se-title-text"),
            (By.CSS_SELECTOR, ".se-title-text"),
            (By.CSS_SELECTOR, ".se-documentTitle .__se-node"),
            (By.CSS_SELECTOR, ".se-title-text .__se-node"),
            (By.XPATH, "//*[contains(@class,'se-documentTitle')]//*[@contenteditable='true']"),
            (By.CSS_SELECTOR, ".se-documentTitle [contenteditable='true']"),
            (By.XPATH, "//*[contains(@class,'se-title-text')]//*[@contenteditable='true']"),
            (By.CSS_SELECTOR, ".se-title-text [contenteditable='true']"),
        ):
            try:
                WebDriverWait(self.driver, 3).until(EC.presence_of_element_located((by, value)))
                for element in self.driver.find_elements(by, value):
                    try:
                        rect = element.rect or {}
                        if element.is_displayed() and float(rect.get("height") or 0) > 8:
                            return element
                    except Exception:
                        continue
            except Exception:
                continue
        return None

    def _js_click_element(self, element) -> bool:
        """JS를 통해 요소를 클릭합니다. .se-container 등 오버레이가 일반 클릭을 차단할 때 사용합니다."""
        try:
            self.driver.execute_script("arguments[0].focus(); arguments[0].click();", element)
            time.sleep(0.2)
            return True
        except Exception:
            return False

    def _type_title_via_js(self, title: str) -> bool:
        """SmartEditor 제목 영역에 JS로 직접 텍스트를 주입합니다.

        Chrome 최신 버전(148+)에서 .se-container 오버레이가 일반 Selenium 클릭/send_keys를
        차단하므로, JS를 통해 .__se-node span에 innerText를 설정한 뒤 input 이벤트를 발화합니다.
        SmartEditor ONE(Naver 블로그 에디터)에서 이 방식으로 제목이 정상 저장됩니다.
        """
        try:
            result = self.driver.execute_script(
                """
const title = arguments[0];
// 제목 노드: .__se-node span > span > p 순으로 탐색
const span = document.querySelector('.se-title-text .__se-node')
          || document.querySelector('.se-title-text span')
          || document.querySelector('.se-title-text p');
if (!span) return false;

// 기존 텍스트 지우고 새 텍스트 설정 (innerText descriptor 우선 사용)
const dp = Object.getOwnPropertyDescriptor(window.HTMLElement.prototype, 'innerText');
if (dp && dp.set) dp.set.call(span, title);
else span.innerText = title;

// 부모 .se-title-text의 se-is-empty 클래스 제거
const titleEl = span.closest('.se-title-text') || document.querySelector('.se-title-text');
if (titleEl) titleEl.classList.remove('se-is-empty');

// SmartEditor에 변경 알림: root contenteditable에 input 이벤트 발화
const root = document.querySelector('[contenteditable="true"]');
if (root) {
    root.dispatchEvent(new InputEvent('input', {
        bubbles: true, cancelable: true, inputType: 'insertText', data: title
    }));
    root.dispatchEvent(new Event('change', {bubbles: true}));
}
return true;
""",
                title,
            )
            return bool(result)
        except Exception:
            return False

    def _type_title_via_keyboard(self, title: str) -> bool:
        """SmartEditor 제목 영역에 실제 키보드 이벤트로 제목을 입력한다.

        JS innerText 주입은 화면 DOM에는 보이지만 네이버 저장 모델에 반영되지 않아
        임시저장 목록에서 '제목 없음'으로 남을 수 있다. 제목은 저장/발행 안정성을
        위해 실제 키보드 이벤트를 최우선으로 사용한다.
        """
        element = self._find_title_element()
        if element is None:
            return False
        text = self._normalize_keyboard_text(title)
        try:
            ActionChains(self.driver).move_to_element(element).click().perform()
            time.sleep(0.35)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform()
            time.sleep(0.2)
            for char in text:
                ActionChains(self.driver).send_keys(char).perform()
                time.sleep(random.uniform(0.01, 0.025))
            time.sleep(0.5)
            return title[:12] in self._read_title_text()
        except Exception:
            pass
        try:
            self._js_click_element(element)
            time.sleep(0.25)
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(Keys.DELETE)
            time.sleep(0.2)
            element.send_keys(text)
            time.sleep(0.5)
            return title[:12] in self._read_title_text()
        except Exception:
            return False

    def _type_title(self, title: str) -> None:
        """현재 컨텍스트에서 제목을 입력합니다 (_ensure_editor_ready 호출 후 사용)."""
        # 0. 클립보드 붙여넣기 우선 (IME 안전 + 포커스 흔들림에도 안정적, 저장모델 반영됨)
        element = self._find_title_element()
        if element is not None:
            try:
                self._js_click_element(element)
                time.sleep(0.2)
                try:
                    ActionChains(self.driver).move_to_element(element).click().perform()
                except Exception:
                    pass
                time.sleep(0.2)
                self._send_shortcut(Keys.CONTROL, "a")
                self._send_shortcut(Keys.DELETE)
                time.sleep(0.15)
                self._paste_segment(self._normalize_keyboard_text(title))
                time.sleep(0.4)
                if title[:12] in self._read_title_text():
                    return
            except Exception:
                pass
        # 1. JS로 제목 영역 포커스
        self._focus_title()
        # 2. 실제 키보드 이벤트 입력 (네이버 저장 모델 반영 우선)
        if self._type_title_via_keyboard(title):
            time.sleep(0.3)
            if title[:12] in self._read_title_text():
                return
        # 3. JS 클릭 + element.send_keys 시도 (폴백)
        element = self._find_title_element()
        if element is not None:
            try:
                self._js_click_element(element)
                element.send_keys(self._normalize_keyboard_text(title))
                time.sleep(0.5)
                if title[:12] in self._read_title_text():
                    return
            except Exception:
                pass
            try:
                self._js_click_element(element)
                time.sleep(0.2)
                for char in self._normalize_keyboard_text(title):
                    ActionChains(self.driver).send_keys(char).perform()
                    time.sleep(random.uniform(0.012, 0.035))
                time.sleep(0.5)
                if title[:12] in self._read_title_text():
                    return
            except Exception:
                pass
        # 4. 마지막: 포커스된 곳에 타이핑 (최후 수단)
        self._type_text_like_human(title)
        time.sleep(0.5)

    def _read_title_text(self) -> str:
        js = """
const roots=Array.from(document.querySelectorAll('.se-documentTitle,.se-title-text'));
const clean=s=>(s||'').replace(/\\s+/g,' ').trim();
const isUiText=t=>!t||t==='제목'||t.includes('배경 사진')||t.includes('삭제')||t.includes('사진 삭제');
const values=[];
for(const root of roots){
  const nodes=Array.from(root.querySelectorAll('[contenteditable="true"],.se-text-paragraph'));
  if(root.classList && root.classList.contains('se-title-text')) nodes.push(root);
  for(const n of nodes){
    const t=clean(n.innerText||n.textContent||n.value||'');
    if(isUiText(t))continue;
    values.push(t);
  }
}
values.sort((a,b)=>a.length-b.length);
return values.find(v=>v.length>=2)||'';
"""
        try:
            return str(self.driver.execute_script(js) or "").strip()
        except Exception:
            return ""

    def _ensure_title_written(self, title: str) -> tuple[bool, str]:
        probe = title[:12]
        actual = ""
        for attempt in range(3):
            actual = self._read_title_text()
            if probe and probe in actual:
                return True, actual
            # 재시도: 실제 키보드 입력 우선
            if self._type_title_via_keyboard(title):
                time.sleep(0.5)
                continue
            self._focus_title()
            self._type_text_like_human(title)
            time.sleep(0.6)

        actual = self._read_title_text()
        return (bool(probe and probe in actual), actual)

    # ─── 본문 입력 ─────────────────────────────────────────────────────────

    def _focus_body(self) -> None:
        self._ensure_editor_ready()
        js = """
const selectors = [
  '.se-component.se-text .se-text-paragraph',
  '.se-component-content [contenteditable="true"]',
  '.se_sectionArea [contenteditable="true"]'
];
for (const selector of selectors) {
  const nodes = Array.from(document.querySelectorAll(selector));
  const target = nodes.find(node => !node.closest('.se-documentTitle,.se-title-text'));
  if (!target) continue;
  if (target.scrollIntoView) target.scrollIntoView({block:'center', inline:'nearest'});
  target.focus();
  target.click();
  return true;
}
const candidates = Array.from(document.querySelectorAll('[contenteditable="true"]'));
const fallback = candidates.find(node => !node.closest('.se-documentTitle,.se-title-text'));
if (fallback) {
  if (fallback.scrollIntoView) fallback.scrollIntoView({block:'center', inline:'nearest'});
  fallback.focus();
  fallback.click();
  return true;
}
return false;
"""
        last_error = None
        for attempt in range(4):
            try:
                if self.driver.execute_script(js):
                    time.sleep(0.3)
                    return
                if attempt == 1:
                    ActionChains(self.driver).send_keys(Keys.TAB).perform()
                    time.sleep(0.3)
            except Exception as exc:
                last_error = exc
            time.sleep(0.4)
        raise last_error or RuntimeError("본문 영역을 찾지 못했습니다.")

    def _type_text_like_human(self, text: str) -> None:
        clean = self._normalize_keyboard_text(re.sub(r"<[^>]+>", "", text))
        if not clean:
            return
        self._bring_chrome_to_front()
        for char in clean:
            ActionChains(self.driver).send_keys(char).perform()
            if char.isspace():
                time.sleep(random.uniform(0.008, 0.018))
            else:
                time.sleep(random.uniform(0.012, 0.035))

    def _normalize_keyboard_text(self, text: str) -> str:
        replacements = {
            "\u2014": "-",
            "\u2013": "-",
            "\u2212": "-",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u00a0": " ",
        }
        return "".join(replacements.get(ch, ch) for ch in text or "")

    def _send_shortcut(self, *keys: str) -> None:
        actions = ActionChains(self.driver)
        for key in keys[:-1]:
            actions.key_down(key)
        actions.send_keys(keys[-1])
        for key in reversed(keys[:-1]):
            actions.key_up(key)
        actions.perform()
        time.sleep(0.08)

    def _set_text_color(self, color: str) -> None:
        wanted = color.strip().lower()
        open_js = """
const btn = document.querySelector('.se-font-color-toolbar-button, [data-name="font-color"] .se-property-toolbar-color-picker-button');
if (!btn) return false;
btn.click();
return true;
"""
        pick_js = """
const wanted = arguments[0];
const candidates = Array.from(document.querySelectorAll('.se-color-palette, button[title^="#"], button[data-color^="#"]'));
const target = candidates.find(node => {
  const values = [
    node.getAttribute('title'),
    node.getAttribute('data-color'),
    node.innerText,
    node.textContent
  ].map(value => (value || '').trim().toLowerCase());
  return values.includes(wanted);
});
if (!target) return false;
target.click();
return true;
"""
        try:
            if not self.driver.execute_script(open_js):
                return
            time.sleep(0.2)
            self.driver.execute_script(pick_js, wanted)
            time.sleep(0.12)
        except Exception:
            pass

    def _set_font_size(self, size: str) -> None:
        wanted = f"fs{str(size).strip().replace('fs', '')}"
        open_js = """
const btn = document.querySelector('.se-font-size-code-toolbar-button, [data-name="font-size-code"] .se-property-toolbar-label-select-button');
if (!btn) return false;
btn.click();
return true;
"""
        pick_js = """
const wanted = arguments[0];
const candidates = Array.from(document.querySelectorAll('.se-toolbar-option-font-size-code button, button[class*="font-size-code-fs"], button[data-value*="fs"]'));
const target = candidates.find(node => {
  const values = [
    node.getAttribute('data-value'),
    node.getAttribute('data'),
    node.getAttribute('class'),
    node.innerText,
    node.textContent
  ].map(value => (value || '').trim().toLowerCase());
  return values.some(value => value.includes(wanted));
});
if (!target) return false;
target.click();
return true;
"""
        try:
            if not self.driver.execute_script(open_js):
                return
            time.sleep(0.2)
            self.driver.execute_script(pick_js, wanted)
            time.sleep(0.12)
        except Exception:
            pass

    def _insert_bold_via_html(self, text: str) -> bool:
        """Ctrl+B 토글은 붙여넣기 직후 상태 확인이 불안정해서(레이스 컨디션으로
        꺼짐 토글이 씹혀 이후 본문 전체가 계속 굵게 나오는 버그, 2026-07-02) 색 없이
        굵게만 필요한 구간(소제목)은 토글 없이 <b> HTML을 직접 삽입해 확실하게 처리한다.

        insertHTML 자체가 가끔(레이스로 추정) 씹혀서 <b> 없이 평문으로 들어가는 경우가
        확인됨(예: 세 번째 소제목 "| 앞으로는?"만 굵게 처리 누락, 2026-07-02) — 삽입 후
        실제 DOM에 <b>가 붙었는지 검증하고, 없으면 재시도한다.

        반대 방향 버그도 있었음: insertHTML 직후 커서가 <b> 태그 안쪽에 그대로 남아서,
        바로 이어서 입력되는(이미지 삽입 후 이어지는) 일반 본문까지 굵게 상속되는 경우
        (예: "왜 중요할까요?" 바로 다음 본문 문단이 통째로 굵게 나옴, 2026-07-02).
        처음엔 이걸 execCommand('bold') 토글로 껐는데, 그 토글이 방금 넣은 <b> 자체를
        다시 벗겨버리는 경우가 있었음(굵게 안 된 상태로 되돌아감, 같은 날 재확인) —
        토글은 아예 쓰지 않는다.

        한 번 더 문제가 있었음: JS로 window.getSelection()/Range를 직접 조작해 커서를
        굵지 않은 spacer로 옮기는 방식을 썼더니, 네이버 스마트에디터가 자체적으로 관리하는
        내부 커서 상태와 실제 브라우저 Selection이 어긋나서, 그 다음 ActionChains의 네이티브
        Enter 키 입력이 새 문단을 못 만들고 이후 텍스트가 전부 한 문단에 뭉쳐버리는 심각한
        레이스가 발생함(소제목+본문 통째로 merge, 이미지 순서도 꼬임, 2026-07-02).
        JS로 Selection을 건드리지 않고, 삽입 직후 네이티브 키보드 이벤트(End 키)만으로
        커서를 <b> 밖으로 빼내 스마트에디터 자체 이벤트 리스너가 정상적으로 인식하게 한다."""
        js = """
const text = arguments[0];
const esc = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
return document.execCommand('insertHTML', false, '<b>' + esc + '</b>');
"""
        verify_js = """
const text = arguments[0];
const frame = document.querySelector('iframe.se-iframe, iframe[name="mainFrame"]');
const doc = frame ? frame.contentDocument : document;
const bolds = doc.querySelectorAll('b');
for (const b of bolds) {
  if (b.textContent && b.textContent.trim() === text.trim()) return true;
}
return false;
"""
        # 삽입 자체는 씹히지 않고 텍스트는 들어가는데 <b> 래핑만 누락되는 경우가 있어서
        # (재시도로 insertHTML을 다시 부르면 텍스트가 중복 삽입됨) — 검증 실패 시에는
        # 이미 들어간(굵게 안 된) 노드를 찾아 <b>로 감싸는 DOM 보정으로 처리한다.
        repair_js = """
const text = arguments[0];
const frame = document.querySelector('iframe.se-iframe, iframe[name="mainFrame"]');
const doc = frame ? frame.contentDocument : document;
const spans = doc.querySelectorAll('span.__se-node, p span');
for (const el of spans) {
  if (el.textContent && el.textContent.trim() === text.trim() && !el.querySelector('b') && el.closest('b') === null) {
    el.innerHTML = '<b>' + el.innerHTML + '</b>';
    return true;
  }
}
return false;
"""
        try:
            self.driver.execute_script(js, text)
        except Exception:
            return False
        # 커서를 <b> 밖으로 — 네이티브 End 키(실제 브라우저 키 이벤트)만 사용, JS로
        # Selection/Range를 직접 건드리지 않는다 (스마트에디터 내부 커서 상태와 어긋나서
        # 이후 Enter가 새 문단을 못 만드는 심각한 레이스가 있었음, 2026-07-02).
        try:
            ActionChains(self.driver).send_keys(Keys.END).perform()
        except Exception:
            pass
        time.sleep(0.15)
        try:
            if bool(self.driver.execute_script(verify_js, text)):
                return True
        except Exception:
            pass
        # 보정 시도
        try:
            self.driver.execute_script(repair_js, text)
            time.sleep(0.15)
            ok = bool(self.driver.execute_script(verify_js, text))
            try:
                ActionChains(self.driver).send_keys(Keys.END).perform()
            except Exception:
                pass
            return ok
        except Exception:
            return False

    def _strip_stray_bold(self) -> None:
        """저장/발행 직전 최종 안전망: "|"로 시작하는 소제목만 굵게, 나머지는 전부
        기본 글씨가 되도록 양방향으로 강제 정리한다(2026-07-02).
        - 소제목이 아닌데 굵게 새어 들어간 것 → 벗김(그동안 여러 번 재발한 문제)
        - 소제목인데 insertHTML이 씹혀서 안 굵게 들어간 것 → 굵게 강제 적용
          (특히 마지막 소제목 "| 앞으로는?"이 몇 차례 테스트에서 계속 안 굵게 남는
          현상이 있었음 — insertHTML 단계의 검증/재시도만으로는 못 잡아서 저장 직전
          문단 단위 최종 스윕으로 한 번 더 확정 처리)."""
        js = """
const frame = document.querySelector('iframe.se-iframe, iframe[name="mainFrame"]');
const doc = frame ? frame.contentDocument : document;
let unbolded = 0, bolded = 0;
// 1) 소제목이 아닌데 굵은 것 -> 벗김
// 2026-07-14: <b> 태그만 검사했더니, 토글(Ctrl+B) 상태가 새서 굵어진 본문이
// <strong>이나 인라인 style="font-weight"로 들어간 경우를 놓쳐서 본문이 통째로
// 굵게 남는 사고가 있었음(소제목은 안 굵고 본문만 굵은, 완전히 뒤바뀐 형태로 발행됨)
// — <b>/<strong>/굵은 인라인 스타일을 모두 검사 대상에 포함한다.
const boldEls = Array.from(doc.querySelectorAll('b, strong, [style*="font-weight"]'));
for (const b of boldEls) {
  const t = (b.textContent || '').trim();
  if (t.startsWith('|')) continue;
  if (b.tagName === 'B' || b.tagName === 'STRONG') {
    const parent = b.parentNode;
    if (!parent) continue;
    while (b.firstChild) parent.insertBefore(b.firstChild, b);
    parent.removeChild(b);
  } else {
    b.style.fontWeight = '';
  }
  unbolded++;
}
// 2) "|"로 시작하는 문단인데 굵게 안 된 것 -> 강제로 굵게
const paras = doc.querySelectorAll('.se-text-paragraph');
for (const p of paras) {
  const t = (p.textContent || '').trim();
  if (!t.startsWith('|')) continue;
  if (p.querySelector('b')) continue;  // 이미 굵음
  const spans = p.querySelectorAll('span.__se-node');
  for (const sp of spans) {
    if (!sp.textContent || !sp.textContent.trim()) continue;
    sp.innerHTML = '<b>' + sp.innerHTML + '</b>';
    bolded++;
  }
}
return unbolded + '/' + bolded;
"""
        try:
            result = self.driver.execute_script(js)
            unbolded, bolded = (result or "0/0").split("/")
            if int(unbolded) or int(bolded):
                self._log(f"[naver] 소제목 굵게 최종 정리: 잘못 굵은 곳 {unbolded}곳 해제, 안 굵은 소제목 {bolded}곳 보정")
        except Exception:
            pass

    def _type_styled_segment(self, text: str, *, bold: bool = False, color: str | None = None, font_size: str | None = None) -> None:
        if not text:
            return
        if font_size and str(font_size) != DEFAULT_FONT_SIZE:
            self._set_font_size(font_size)
            self._size_dirty = True   # 이후 일반 텍스트에서 기본크기 재적용 보장
        if color:
            self._set_text_color(color)
        normalized = self._normalize_keyboard_text(text)
        if bold and not color and self._insert_bold_via_html(normalized):
            pass  # HTML 삽입으로 이미 굵게 처리됨 — 토글 불필요
        else:
            if bold:
                self._send_shortcut(Keys.CONTROL, "b")
            # 강조 구간은 '붙여넣기'로 원자적 입력 — char 단위 타이핑 시 툴바 드롭다운 직후
            # 포커스/IME 경합으로 같은 단어가 두 번 들어가는 중복(예: 임영웅임영웅) 방지.
            self._paste_segment(normalized)
            if bold:
                self._send_shortcut(Keys.CONTROL, "b")
        if color:
            self._set_text_color(DEFAULT_TEXT_COLOR)
        if font_size and str(font_size) != DEFAULT_FONT_SIZE:
            # 1차 리셋 시도(가끔 툴바에서 누락 → _size_dirty로 다음 일반 텍스트에서 재보강)
            self._set_font_size(DEFAULT_FONT_SIZE)

    def _next_text_color(self, style: str) -> str:
        color = READABLE_TEXT_COLORS[self._color_cursor % len(READABLE_TEXT_COLORS)]
        self._color_cursor = (self._color_cursor + 1) % len(READABLE_TEXT_COLORS)
        return color

    def _type_rich_text_like_human(self, text: str) -> None:
        """강조 마커를 폰트 강조/색/크기로 변환해 입력. 강조 후엔 기본 폰트로 복귀.
        지원 마커(조합형):
          **굵게** / __굵게__         → 굵게
          {{color:문구}}              → 색
          {{point:문구}}              → 굵게 + 색
          {{big:문구}}                → 크게 (크기만)
          {{bigb:문구}}               → 크게 + 굵게
          {{head:문구}}               → 크게 + 굵게 + 색 (소제목)
        """
        parts = re.split(r"(\{\{(?:big|bigb|head|point|color):.+?\}\}|\*\*.+?\*\*|__.+?__)", text)
        for part in parts:
            if not part:
                continue
            rich_match = re.fullmatch(r"\{\{(big|bigb|head|point|color):(.+?)\}\}", part)
            if rich_match:
                style, rich_text = rich_match.group(1), rich_match.group(2).strip()
                if style == "head":
                    self._type_styled_segment(rich_text, bold=True, color=self._next_text_color(style), font_size=HEADING_FONT_SIZE)
                elif style == "bigb":
                    # 소제목(오늘의 사실/왜중요/앞으는)은 사진 바로 아래든 본문 바로 아래든
                    # 항상 표준 문단 간격보다 한 줄 더 띄운다(2026-07-02 피드백)
                    # 2026-07-02: 이 ENTER 직후 곧바로 타이핑을 시작하면 이전 문단과 합쳐지거나
                    # 소제목 텍스트 자체가 씹히는 레이스가 있었음 — 대기를 늘려서 문단 분리가
                    # 확정된 뒤에 타이핑하도록 함.
                    ActionChains(self.driver).send_keys(Keys.ENTER).perform()
                    time.sleep(0.35)
                    self._type_styled_segment(rich_text, bold=True, font_size=HEADING_FONT_SIZE)
                elif style == "big":
                    self._type_styled_segment(rich_text, font_size=HEADING_FONT_SIZE)
                elif style == "point":
                    self._type_styled_segment(rich_text, bold=True, color=self._next_text_color(style))
                else:  # color
                    self._type_styled_segment(rich_text, color=self._next_text_color(style))
                continue
            is_bold = (part.startswith("**") and part.endswith("**")) or (part.startswith("__") and part.endswith("__"))
            if is_bold and len(part) > 4:
                bold_text = part[2:-2].strip()
                if bold_text:
                    self._type_styled_segment(bold_text, bold=True)
                continue
            # 일반 텍스트 — 직전 큰 폰트가 리셋 안 됐을 수 있으니 기본크기 재적용(이중 보강)
            # ★안전망: 변환 경로를 못 거친 마커가 평문에 남으면 '내부 텍스트만' 남기고 제거(소스 노출 방지)
            plain = re.sub(r"\{\{(?:big|bigb|head|point|color):(.+?)\}\}", r"\1", part)
            plain = re.sub(r"(\*\*|__)", "", plain)
            if self._size_dirty:
                self._set_font_size(DEFAULT_FONT_SIZE)
                self._size_dirty = False
            self._type_text_like_human(plain)

    def _type_text_at_current_cursor(self, text: str, strip_photo_tokens: bool = True) -> None:
        clean = re.sub(r"^#{1,3}\s+", "", text or "", flags=re.MULTILINE).strip()
        if strip_photo_tokens:
            clean = re.sub(r"\[photo_\d{2}\.jpg\]", "", clean)
        paragraphs = re.split(r"\n{2,}", clean)
        for pidx, paragraph in enumerate(paragraphs):
            lines = [line.rstrip() for line in paragraph.splitlines()]
            if not any(line.strip() for line in lines):
                continue
            for lidx, line in enumerate(lines):
                stripped = line.strip()
                if stripped:
                    self._type_rich_text_like_human(stripped)
                    if "map.naver.com" in stripped:
                        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
                        time.sleep(1.2)
                if lidx < len(lines) - 1:
                    ActionChains(self.driver).key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT).perform()
                    time.sleep(0.12)
            if pidx < len(paragraphs) - 1:
                ActionChains(self.driver).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
                time.sleep(0.25)

    def _paste_segment(self, text: str) -> None:
        """짧은 강조 구간을 클립보드 붙여넣기로 원자적 입력(중복 방지). 활성 서식(굵게/색/크기) 유지."""
        if not text:
            return
        try:
            self._copy_text_to_clipboard(text)
            time.sleep(0.1)
            self._send_shortcut(Keys.CONTROL, "v")
            time.sleep(0.18)
        except Exception:
            # 클립보드 실패 시 기존 타이핑 폴백
            self._type_text_like_human(text)

    def _copy_text_to_clipboard(self, text: str) -> None:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()

    def _focus_body_end(self) -> bool:
        self._ensure_editor_ready()
        js = """
const editables = Array.from(document.querySelectorAll('[contenteditable="true"]'))
  .filter(node => !node.closest('.se-documentTitle,.se-title-text'));
if (!editables.length) return false;
let target = editables[editables.length - 1];
const textBlocks = editables.filter(node => node.closest('.se-component.se-text,.se-text-paragraph,.se-module-text'));
if (textBlocks.length) target = textBlocks[textBlocks.length - 1];
if (target.scrollIntoView) target.scrollIntoView({block:'center'});
target.focus();
target.click();
const sel = window.getSelection();
const range = document.createRange();
range.selectNodeContents(target);
range.collapse(false);
sel.removeAllRanges();
sel.addRange(range);
return true;
"""
        for _ in range(4):
            try:
                if self.driver.execute_script(js):
                    time.sleep(0.25)
                    return True
            except Exception:
                pass
            self._focus_body()
            time.sleep(0.25)
        return False

    def _selenium_click_body_end(self) -> bool:
        """Selenium WebElement.click()으로 본문 마지막 텍스트 요소를 클릭합니다.

        JS .focus()만으로는 ActionChains의 active element가 바뀌지 않기 때문에,
        이미지 삽입 이후 실제 OS 키보드 포커스를 텍스트 영역으로 이전하려면
        Selenium 레벨 클릭이 필요합니다.
        """
        selectors = [
            '.se-component.se-text .se-text-paragraph',
            '.se-module-text [contenteditable="true"]',
            '.se-component-content [contenteditable="true"]',
            '.se_sectionArea [contenteditable="true"]',
        ]
        for sel in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, sel)
                body_els = []
                for el in elements:
                    try:
                        in_title = self.driver.execute_script(
                            "return !!arguments[0].closest('.se-documentTitle,.se-title-text');", el
                        )
                        if not in_title:
                            body_els.append(el)
                    except Exception:
                        pass
                if body_els:
                    target = body_els[-1]
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", target
                    )
                    time.sleep(0.2)
                    target.click()   # Selenium click → OS 포커스 이전
                    time.sleep(0.3)
                    return True
            except Exception:
                continue
        return False

    def _paste_body_text(self, text: str) -> bool:
        clean = re.sub(r"^#{1,3}\s+", "", text, flags=re.MULTILINE).strip()
        if not clean:
            return True
        self._focus_body_end()
        before = self._read_body_text()
        self._copy_text_to_clipboard(clean)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()
        time.sleep(1.0)
        after = self._read_body_text()
        probe = clean[: min(20, len(clean))]
        if probe and probe in after and len(after) >= len(before):
            return True
        return False

    def _read_body_text(self) -> str:
        js = """
const parts = [];
document.querySelectorAll('.se-component.se-text, .se-module-text:not(.se-title-text), .se-component:not(.se-documentTitle) [contenteditable="true"], [contenteditable="true"]').forEach(node => {
  if (node.closest('.se-documentTitle,.se-title-text')) return;
  const text = (node.innerText || node.textContent || '').trim();
  if (text) parts.push(text);
});
return parts.join('\\n').trim();
"""
        def _read():
            return str(self.driver.execute_script(js) or "").strip()

        results = self._run_in_contexts(_read)
        longest = ""
        for result in results:
            if result and len(result) > len(longest):
                longest = result
        return longest.strip()

    def _verify_body_written(self, expected: str) -> tuple[bool, str]:
        expected_clean = re.sub(r"^#{1,3}\s+", "", expected or "", flags=re.MULTILINE)
        expected_clean = re.sub(r"\[photo_\d{2}\.jpg\]", " ", expected_clean)
        expected_clean = re.sub(r"\{\{(?:big|point|color):(.+?)\}\}", r"\1", expected_clean)
        expected_clean = re.sub(r"(\*\*|__)", "", expected_clean)
        expected_clean = "\n".join(line for line in expected_clean.splitlines() if "map.naver.com" not in line)
        expected_clean = re.sub(r"\s+", " ", expected_clean).strip()
        actual_clean = re.sub(r"\s+", " ", self._read_body_text()).strip()
        if not expected_clean:
            return False, "expected-empty"
        probes = [
            expected_clean[:40].strip(),
            expected_clean[max(0, len(expected_clean) // 2 - 20): max(0, len(expected_clean) // 2 - 20) + 40].strip(),
            expected_clean[-40:].strip(),
        ]
        probes = [probe for probe in probes if len(probe) >= 8]
        if actual_clean and any(probe in actual_clean for probe in probes):
            return True, actual_clean[:160]
        return False, actual_clean[:160] if actual_clean else "NONE"

    def _type_body_text(self, text: str) -> None:
        if TEXT_ONLY_MODE:
            self._type_text_at_current_cursor(text)
            return
        clean = re.sub(r"^#{1,3}\s+", "", text, flags=re.MULTILINE).strip()
        clean = re.sub(r"\[photo_\d{2}\.jpg\]", "", clean)
        paragraphs = re.split(r"\n{2,}", clean)
        for pidx, paragraph in enumerate(paragraphs):
            lines = [line.rstrip() for line in paragraph.splitlines()]
            if not any(line.strip() for line in lines):
                continue
            self._focus_body_end()
            for lidx, line in enumerate(lines):
                stripped = line.strip()
                if stripped:
                    self._type_rich_text_like_human(stripped)
                if lidx < len(lines) - 1:
                    ActionChains(self.driver).key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT).perform()
                    time.sleep(0.12)
            if pidx < len(paragraphs) - 1:
                ActionChains(self.driver).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
                time.sleep(0.25)

    def _count_editor_images(self) -> int:
        js = """
const selectors = ['.se-component img','.se-image-resource','.se-section-image img','.se-module-image img','img'];
const seen = new Set();
for (const selector of selectors) {
  document.querySelectorAll(selector).forEach(node => {
    if (node.closest('.se-documentTitle,.se-title-text')) return;
    const src = (node.getAttribute('src') || '').trim();
    const cls = (node.className || '').toString();
    if (!src && !cls) return;
    seen.add(src || cls);
  });
}
return seen.size;
"""
        try:
            return int(self.driver.execute_script(js) or 0)
        except Exception:
            return 0

    def _copy_image_to_clipboard(self, image_path: Path) -> None:
        import win32clipboard
        output = io.BytesIO()
        with Image.open(image_path) as img:
            img.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]  # BMP 헤더 14바이트 제거 → CF_DIB 형식
        output.close()
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        finally:
            win32clipboard.CloseClipboard()

    def _select_photo_token(self, token: str) -> bool:
        js = """
const token = arguments[0];
const roots = Array.from(document.querySelectorAll('.se-component.se-text, .se-module-text, [contenteditable="true"]'))
  .filter(node => !node.closest('.se-documentTitle,.se-title-text'));
for (const root of roots) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const idx = (node.nodeValue || '').indexOf(token);
    if (idx < 0) continue;
    const range = document.createRange();
    range.setStart(node, idx);
    range.setEnd(node, idx + token.length);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const holder = node.parentElement || root;
    if (holder.scrollIntoView) holder.scrollIntoView({block:'center', inline:'nearest'});
    if (holder.focus) holder.focus();
    return true;
  }
}
return false;
"""
        try:
            return bool(self.driver.execute_script(js, token))
        except Exception:
            return False

    def _remove_photo_token_text(self, token: str) -> None:
        js = """
const token = arguments[0];
const roots = Array.from(document.querySelectorAll('.se-component.se-text, .se-module-text, [contenteditable="true"]'))
  .filter(node => !node.closest('.se-documentTitle,.se-title-text'));
for (const root of roots) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const value = node.nodeValue || '';
    if (!value.includes(token)) continue;
    node.nodeValue = value.replace(token, '');
    const target = node.parentElement || root;
    target.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
    return true;
  }
}
return false;
"""
        try:
            self.driver.execute_script(js, token)
        except Exception:
            pass

    def _insert_image_at_photo_token(self, token: str, image_path: Path) -> tuple[bool, str]:
        for attempt in range(3):
            self._ensure_editor_ready()
            if not self._select_photo_token(token):
                time.sleep(0.4)
                continue
            before = self._count_editor_images()
            self._copy_image_to_clipboard(image_path)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()
            time.sleep(5)
            after = self._count_editor_images()
            if after > before:
                self._remove_photo_token_text(token)
                try:
                    ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                except Exception:
                    pass
                time.sleep(0.4)
                return True, f"{token} -> {image_path.name}"
            time.sleep(0.6)
        return False, f"{token} 위치에 이미지 삽입 실패: {image_path.name}"

    def _insert_images_after_text(self, image_map: dict[str, Path]) -> tuple[bool, str]:
        inserted: list[str] = []
        for key in sorted(image_map):
            image_path = image_map[key]
            if not image_path.exists():
                continue
            ok, msg = self._insert_image_at_photo_token(f"[{key}]", image_path)
            if not ok:
                return False, msg
            inserted.append(msg)
        return True, "사진 삽입 완료: " + ", ".join(inserted)

    def _insert_image(self, image_path: Path) -> tuple[bool, str]:
        """이미지를 클립보드로 붙여넣고 실제 삽입 여부를 검증합니다 (DSM과 동일).

        고정 5초 대기 대신 0.5초 간격으로 최대 15초간 폴링합니다.
        """
        for attempt in range(2):
            self._focus_body()
            before = self._count_editor_images()
            self._copy_image_to_clipboard(image_path)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()
            for _ in range(30):
                time.sleep(0.5)
                if self._count_editor_images() > before:
                    return True, "image-pasted"

            self._bring_chrome_to_front()
            self._focus_body()
            pyautogui.hotkey("ctrl", "v")
            for _ in range(30):
                time.sleep(0.5)
                if self._count_editor_images() > before:
                    return True, "image-pasted-os-hotkey"

            if attempt == 0:
                time.sleep(1.0)
        return False, "image-paste-timeout"

    def _prepare_body_after_image(self) -> bool:
        self._ensure_editor_ready()
        js = """
const editables = Array.from(document.querySelectorAll('[contenteditable="true"]'))
  .filter(node => !node.closest('.se-documentTitle,.se-title-text'));
if (!editables.length) return false;
let target = editables[editables.length - 1];
const textBlocks = editables.filter(node => node.closest('.se-component.se-text,.se-text-paragraph,.se-module-text'));
if (textBlocks.length) target = textBlocks[textBlocks.length - 1];
if (target.scrollIntoView) target.scrollIntoView({block:'center', inline:'nearest'});
target.focus();
target.click();
const sel = window.getSelection();
const range = document.createRange();
range.selectNodeContents(target);
range.collapse(false);
sel.removeAllRanges();
sel.addRange(range);
return true;
"""
        for _ in range(3):
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.2)
                # 2026-07-02: 사진 바로 아래 문단이 너무 멀어 보인다는 피드백으로 엔터 1번만
                # (사진과 다음 내용이 붙어 보이도록) — 문단 간 표준 간격은 그대로 2번 유지됨
                ActionChains(self.driver).send_keys(Keys.ENTER).perform()
                time.sleep(0.35)
                if self.driver.execute_script(js):
                    # 2026-07-02: 이미지 직후 다음 문단(특히 소제목) 타이핑이 씹히거나
                    # 이전 문단과 합쳐지는 레이스가 있었음 — 여기서 커서 배치가 완전히
                    # 안정되기 전에 다음 타이핑이 시작되는 게 원인으로 보여 대기를 늘림.
                    time.sleep(0.5)
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        return self._focus_body_end()

    def _insert_body_segmented_with_images(self, body: str, image_map: dict[str, Path]) -> tuple[bool, str]:
        """원고 위치대로 텍스트와 이미지를 번갈아 삽입합니다.

        각 이미지 삽입 후 _prepare_body_after_image() + _selenium_click_body_end()로
        Selenium active element를 텍스트 영역으로 복귀시킨 뒤 다음 텍스트 구간을 타이핑합니다.
        """
        self._ensure_editor_ready()
        self._focus_body()
        self._selenium_click_body_end()
        chunks = re.split(r"(\[photo_\d{2}\.jpg\])", body)
        inserted: list[str] = []
        first_text_chunk = True

        for chunk in chunks:
            value = chunk.strip()
            if not value:
                continue

            # ── 이미지 토큰 ────────────────────────────────────────────────
            if re.fullmatch(r"\[photo_\d{2}\.jpg\]", value):
                key = value.strip("[]")
                image_path = image_map.get(key)
                if image_path and image_path.exists():
                    self._log(f"사진 삽입 중: {image_path.name}")
                    inserted_ok, detail = self._insert_image(image_path)
                    if not inserted_ok:
                        return False, f"이미지 삽입 실패: {image_path.name} ({detail})"
                    inserted.append(image_path.name)
                    # 이미지 컴포넌트 탈출 + Selenium 클릭으로 OS 포커스 복귀
                    self._prepare_body_after_image()
                    self._selenium_click_body_end()
                    time.sleep(0.3)
                continue

            # ── 텍스트 구간 ────────────────────────────────────────────────
            self._ensure_editor_ready()
            if first_text_chunk:
                # 첫 텍스트: publish_draft에서 ENTER로 이미 본문에 커서가 있음
                first_text_chunk = False
            else:
                # 이미지 삽입 후 또는 두 번째 이상 텍스트 구간: Selenium 클릭으로 포커스 보장
                self._focus_body_end()
                self._selenium_click_body_end()

            self._type_text_chunk_with_autolinks(value)
            time.sleep(0.3)

        return True, "본문/사진 분할 입력 완료" + (f" ({', '.join(inserted)})" if inserted else "")

    def _type_text_chunk_with_autolinks(self, value: str) -> None:
        """URL 입력 직후 Enter를 눌러 Smart Editor 링크 변환을 확정한다."""
        # 2026-07-03: "원문:" 뿐 아니라 "한겨레: <url>"처럼 언론사명이 그대로 앞에 붙는
        # 줄도 한 줄로 자동링크 처리 — 예전엔 "원문:"만 인식해서 언론사명을 URL과 별도
        # 줄로 둬야 했는데, 그럼 언론사명 줄과 원문 줄이 붙어 보여서("한겨레원문: ...")
        # 사용자가 언론사명만 남기고 "원문" 단어를 빼고 싶어함 — 라벨을 일반화해서 해결.
        url_line = re.compile(r"^(?:([^:\n]{1,20})\s*:\s*)?(https?://\S+)\s*$")
        pending: list[str] = []

        def flush_pending() -> bool:
            """반환값: 실제로 뭔가 타이핑했는지 여부(직후 줄바꿈이 필요한지 판단용)."""
            text = "\n".join(pending).strip()
            pending.clear()
            if text:
                self._type_text_at_current_cursor(text, strip_photo_tokens=False)
                return True
            return False

        for line in value.splitlines():
            match = url_line.match(line.strip())
            if not match:
                pending.append(line)
                continue
            # 2026-07-03: "{{point:원문 보기}}" 같은 헤더 바로 다음 줄이 URL이면, 헤더 텍스트
            # 타이핑 뒤에 줄바꿈 없이 곧장 붙여써서 "원문 보기연합뉴스: https://..."처럼
            # 이어 붙어 보이는 버그가 있었음 — URL 앞에 일반 텍스트가 있었으면 줄바꿈을 넣는다.
            if flush_pending():
                ActionChains(self.driver).send_keys(Keys.ENTER).perform()
                time.sleep(0.2)
            prefix = match.group(1)
            label = f"{prefix}: " if prefix else ""
            # char 단위 타이핑은 URL처럼 빠르게 연타되는 구간에서 첫 글자가 중복 입력되는
            # 레이스 컨디션이 있었음(예: "https://" → "hhttps://") — 클립보드 붙여넣기로
            # 원자적 입력해 방지.
            self._paste_segment(f"{label}{match.group(2)}")
            ActionChains(self.driver).send_keys(Keys.ENTER).perform()
            time.sleep(0.4)
        flush_pending()

    def _insert_link_line(self, label: str, url: str) -> None:
        safe_url = url.strip()
        if not safe_url:
            return
        self._type_body_text(f"{label or '지도 링크'}\n{safe_url}")

    def _insert_text_with_map_links(self, value: str) -> None:
        pending: list[str] = []
        for line in value.splitlines():
            stripped = line.strip()
            if "map.naver.com" not in stripped:
                pending.append(line)
                continue
            if TEXT_ONLY_MODE:
                before = "\n".join(pending).strip()
                if before:
                    self._focus_body_end()
                    self._type_body_text(before)
                    ActionChains(self.driver).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
                    time.sleep(0.25)
                pending = []
                continue
            before = "\n".join(pending).strip()
            if before:
                self._focus_body_end()
                self._type_body_text(before)
                ActionChains(self.driver).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
                time.sleep(0.25)
            pending = []
            match = re.search(r"https?://\S*map\.naver\.com/\S+", stripped)
            map_url = match.group(0).rstrip(".,)") if match else stripped
            self._focus_body_end()
            self._insert_link_line("일루아 미용실 네이버 지도 바로가기", map_url)
            ActionChains(self.driver).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
            time.sleep(0.25)
        rest = "\n".join(pending).strip()
        if rest:
            self._focus_body_end()
            self._type_body_text(rest)

    def _insert_images_first_mode(self, body: str, image_map: dict[str, Path]) -> tuple[bool, str]:
        """Phase 1-A: 머리 사진 먼저 → 본문 텍스트 → 미용실 사진 순서로 입력합니다.

        흐름:
          1. photo_01 ~ photo_03 (머리 이미지) 순서대로 삽입
          2. 본문 텍스트 전체 타이핑 (photo 토큰 전부 제거)
          3. photo_04 (미용실 이미지) 맨 마지막 삽입
        """
        hair_keys = sorted(k for k in image_map if k != "photo_04.jpg")
        salon_key = "photo_04.jpg" if "photo_04.jpg" in image_map else None

        # ── 1. 머리 이미지 먼저 삽입 ──────────────────────────────────────
        inserted_hair: list[str] = []
        for key in hair_keys:
            image_path = image_map[key]
            if not image_path.exists():
                self._log(f"이미지 파일 없음 (스킵): {image_path.name}")
                continue
            self._log(f"머리 사진 삽입 중: {image_path.name}")
            ok, detail = self._insert_image(image_path)
            if not ok:
                return False, f"머리 사진 삽입 실패: {image_path.name} ({detail})"
            inserted_hair.append(image_path.name)
            # 이미지 컴포넌트 탈출 후 새 문단 생성
            self._prepare_body_after_image()
            time.sleep(0.4)

        # ── 2. 본문 텍스트 입력 (photo 토큰 전부 제거) ────────────────────
        self._log("본문 텍스트 입력 중...")
        self._ensure_editor_ready()
        # JS focus → Selenium WebElement.click() 순서로 OS 포커스 보장
        self._focus_body_end()
        self._selenium_click_body_end()   # ActionChains active element 이전
        time.sleep(0.3)
        self._type_text_at_current_cursor(body, strip_photo_tokens=True)
        time.sleep(0.5)

        # ── 3. 미용실 사진 (photo_04) 맨 마지막 삽입 ─────────────────────
        inserted_salon = False
        if salon_key:
            image_path = image_map[salon_key]
            if image_path.exists():
                self._log(f"미용실 사진 삽입 중: {image_path.name}")
                self._ensure_editor_ready()
                self._focus_body_end()
                self._selenium_click_body_end()
                # 본문 끝 다음 줄에 삽입
                ActionChains(self.driver).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
                time.sleep(0.3)
                ok, detail = self._insert_image(image_path)
                if ok:
                    inserted_salon = True
                    try:
                        ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                        time.sleep(0.3)
                    except Exception:
                        pass
                else:
                    self._log(f"미용실 사진 삽입 실패 (계속 진행): {image_path.name} ({detail})")
            else:
                self._log(f"미용실 이미지 파일 없음 (스킵): {image_path.name}")

        hair_msg = f"머리 사진 {len(inserted_hair)}장" if inserted_hair else "머리 사진 없음"
        salon_msg = "미용실 사진 1장" if inserted_salon else "미용실 사진 없음"
        return True, f"이미지 먼저 삽입 완료 — {hair_msg}, {salon_msg}"

    def _insert_body(self, body: str, image_map: dict[str, Path]) -> tuple[bool, str]:
        # Phase 1-A: 이미지 먼저 삽입 모드 (최우선)
        if IMAGES_FIRST_MODE and image_map:
            return self._insert_images_first_mode(body, image_map)
        if SEGMENTED_IMAGE_MODE and image_map:
            return self._insert_body_segmented_with_images(body, image_map)
        if TEXT_ONLY_MODE:
            self._type_text_at_current_cursor(body, strip_photo_tokens=not INSERT_IMAGES_AFTER_TEXT)
            return True, "본문 입력 완료"
        chunks = re.split(r"(\[photo_\d{2}\.jpg\])", body)
        for chunk in chunks:
            value = chunk.strip()
            if not value:
                continue
            if re.fullmatch(r"\[photo_\d{2}\.jpg\]", value):
                if TEXT_ONLY_MODE:
                    continue
                key = value.strip("[]")
                image_path = image_map.get(key)
                if image_path and image_path.exists():
                    inserted, detail = self._insert_image(image_path)
                    if not inserted:
                        return False, f"이미지 삽입 실패: {image_path.name} ({detail})"
                continue
            if "map.naver.com" in value:
                self._insert_text_with_map_links(value)
                continue
            self._focus_body()
            self._type_body_text(value)
            time.sleep(0.5)
        return True, "본문 입력 완료"

    # ─── 임시저장 ──────────────────────────────────────────────────────────

    _SAVE_COUNT_JS = r"""
const btns=Array.from(document.querySelectorAll('button'));
const b=btns.find(n=>/save_count_btn/.test(n.className||'') ||
  (((n.getAttribute&&n.getAttribute('aria-label'))||'').includes('임시저장 글')));
if(!b) return null;
const s=(b.innerText||'')+' '+(((b.getAttribute&&b.getAttribute('aria-label'))||''));
const m=s.match(/\d+/);
return m?parseInt(m[0],10):null;
"""

    def _read_save_count(self) -> int | None:
        """헤더 '저장' 옆 임시저장 글 개수(예: 88) 읽기. 저장 성공 시 +1 → 검증 기준.
        네이버가 에디터를 iframe에 넣는 경우가 있어 기본+에디터프레임 양쪽에서 찾는다."""
        def _read():
            try:
                v = self.driver.execute_script(self._SAVE_COUNT_JS)
                return int(v) if v is not None else None
            except Exception:
                return None
        for r in self._run_in_contexts(_read):
            if isinstance(r, int):
                return r
        return None

    def _verify_draft_saved(self) -> tuple[bool, str]:
        """저장 완료 '토스트'만 성공으로 인정. (임시저장 목록이 뜬 것은 성공 아님 — 과거 오판 원인)"""
        js = """
const clean=v=>(v||'').replace(/\\s+/g,' ').trim();
const snaps=[];
document.querySelectorAll('[role="status"],[class*="toast"],[class*="noti"],[class*="message"]').forEach(n=>{
  const t=clean(n.innerText); if(t&&!snaps.includes(t))snaps.push(t);
});
return JSON.stringify({snaps});
"""
        keywords = ["임시저장됨", "임시 저장됨", "저장되었습니다", "저장됐습니다", "저장 완료", "임시저장이 완료", "임시저장되었습니다"]
        try:
            data = json.loads(self.driver.execute_script(js) or '{"snaps":[]}')
        except Exception:
            return False, "no-signal"
        combined = " | ".join(data.get("snaps", []))
        for kw in keywords:
            if kw in combined:
                return True, kw
        return False, combined[:120] or "no-toast"

    _SAVE_CLICK_JS = r"""
const btns=Array.from(document.querySelectorAll('button'));
let b=btns.find(n=>/save_btn/.test(n.className||'') && !/save_count/.test(n.className||''));
if(!b) b=btns.find(n=>((n.innerText||'').replace(/\s+/g,''))==='저장' && !/save_count/.test(n.className||''));
if(!b) return false;
b.click(); return true;
"""

    def _click_save_button_dom(self) -> bool:
        """정확히 '저장'(임시저장) 버튼만 클릭. 옆의 목록(save_count) 버튼은 제외.
        기본+에디터프레임 양쪽에서 시도(네이버 iframe 래핑 대응)."""
        def _click():
            try:
                return bool(self.driver.execute_script(self._SAVE_CLICK_JS))
            except Exception:
                return False
        return any(self._run_in_contexts(_click))

    def _save_draft(self) -> tuple[bool, str]:
        self._bring_chrome_to_front()
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        before = self._read_save_count()

        def _confirm(method: str):
            time.sleep(2.5)
            after = self._read_save_count()
            if before is not None and after is not None and after > before:
                return True, f"{method} 임시저장 완료 (목록 {before}→{after})"
            saved, signal = self._verify_draft_saved()
            if saved:
                return True, f"{method} 임시저장 완료 ({signal})"
            return None

        # 1. DOM '저장' 버튼 클릭 (가장 정확)
        if self._click_save_button_dom():
            r = _confirm("저장버튼")
            if r:
                return r

        # 2. Ctrl+S
        try:
            self._ensure_editor_ready()
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("s").key_up(Keys.CONTROL).perform()
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            r = _confirm("Ctrl+S")
            if r:
                return r
        except Exception:
            pass

        # 3. 사용자 등록 좌표 클릭 (설정된 경우)
        sx, sy = self.settings.save_button_x, self.settings.save_button_y
        if sx > 0 and sy > 0:
            try:
                pyautogui.moveTo(sx, sy, duration=0.35)
                time.sleep(0.15)
                pyautogui.click(x=sx, y=sy, duration=0.15)
                r = _confirm("좌표")
                if r:
                    return r
            except Exception:
                pass

        after = self._read_save_count()
        return False, f"임시저장 확인 실패(목록수 {before}→{after}). '저장' 버튼을 못 눌렀거나 저장이 안 됐습니다."

    def _wait_for_editor_idle(self, max_wait: int = 15) -> None:
        """이미지 업로드/로딩 오버레이가 사라질 때까지 대기 (최대 max_wait 초)."""
        LOADING_CHECK_JS = """
(function() {
  // 이미지 업로드 중인 엘리먼트 존재 여부
  const uploading = document.querySelector(
    '[class*="uploading"], [class*="loading"], [class*="progress"], ' +
    '[class*="spinner"], .se-loading, [aria-busy="true"]'
  );
  // 업로드 대기 중인 이미지 (src가 blob: 또는 data:인 경우 = 아직 업로드 중)
  const blobImgs = Array.from(document.querySelectorAll('img[src^="blob:"], img[src^="data:"]'));
  return {uploading: !!uploading, blob_imgs: blobImgs.length};
})()
"""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                self.driver.switch_to.default_content()
                WebDriverWait(self.driver, 3).until(
                    EC.frame_to_be_available_and_switch_to_it((By.ID, "mainFrame"))
                )
                status = self.driver.execute_script(LOADING_CHECK_JS)
                if status and (status.get("uploading") or status.get("blob_imgs", 0) > 0):
                    self._log(f"이미지 업로드 대기 중... ({status})")
                    time.sleep(1)
                    continue
                break
            except Exception:
                break
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

    def _publish_post_via_dom(self) -> tuple[bool, str]:
        """SmartEditor DOM 버튼을 통한 발행 (PyAutoGUI 좌표 불필요).

        Naver SmartEditor의 발행 흐름:
          1. .publish_btn__* 클릭 → 발행 설정 패널 오픈
          2. .confirm_btn__* 클릭 → 전체공개 발행 확정

        이 방식은 Chrome 창 위치/크기에 무관하게 동작합니다.
        """
        # 이미지 업로드 완료 대기
        self._wait_for_editor_idle(max_wait=20)
        time.sleep(1)
        # 발행 패널 오픈 + 확인 버튼 클릭 (querySelectorAll+filter 방식으로 shadow DOM 우회)
        PUBLISH_BTN_JS = """
return (function() {
  var allBtns = Array.from(document.querySelectorAll('button'));
  var getClass = function(b) { return typeof b.className === 'string' ? b.className : String(b.className || ''); };
  var getText  = function(b) { return (b.innerText || b.textContent || '').trim(); };
  var summary = allBtns.slice(0,5).map(function(b){return getClass(b).substring(0,30);}).join('|');
  if (allBtns.length === 0) return 'DIAG:no-buttons';
  // 발행 패널이 이미 열려있는지: confirm_btn 또는 fold_btn 포함 버튼 존재
  var confirmBtn = null; var foldBtn = null;
  for(var i=0;i<allBtns.length;i++){
    var c=getClass(allBtns[i]);
    if(c.indexOf('confirm_btn')!==-1) confirmBtn=allBtns[i];
    if(c.indexOf('fold_btn')!==-1 && c.indexOf('publish')!==-1) foldBtn=allBtns[i];
  }
  if (confirmBtn) {
    return 'panel-existing-confirm:' + getClass(confirmBtn).substring(0,50);
  }
  if (foldBtn) {
    return 'DIAG:fold-only-no-confirm:' + getClass(foldBtn).substring(0,40);
  }
  // 패널 닫혀있음 → publish_btn 클릭해서 패널 열기
  var pubBtn = null;
  for(var j=0;j<allBtns.length;j++){
    var c2=getClass(allBtns[j]);
    if(c2.indexOf('publish_btn')!==-1 && c2.indexOf('fold')===-1 && c2.indexOf('confirm')===-1){
      pubBtn=allBtns[j]; break;
    }
  }
  if (!pubBtn) {
    for(var k=0;k<allBtns.length;k++){
      if(getText(allBtns[k])==='발행' && getClass(allBtns[k]).indexOf('confirm')===-1){ pubBtn=allBtns[k]; break; }
    }
  }
  if (!pubBtn) return 'DIAG:no-pub-btn|' + summary;
  var cls = getClass(pubBtn).substring(0,50);
  try { pubBtn.click(); } catch(e) { return 'click-err:' + String(e); }
  return 'panel-open:' + cls;
})()
"""
        PUBLISH_NOW_JS = """
return (function() {
  var nodes = Array.from(document.querySelectorAll('button,label,a,span,div,input'));
  var textOf = function(n) { return (n.innerText || n.textContent || n.getAttribute('aria-label') || n.getAttribute('title') || n.value || '').trim(); };
  var clsOf = function(n) { return typeof n.className === 'string' ? n.className : String(n.className || ''); };
  var isSelected = function(n) {
    return n.checked === true || n.getAttribute('aria-checked') === 'true' || clsOf(n).indexOf('checked') !== -1 || clsOf(n).indexOf('selected') !== -1 || clsOf(n).indexOf('active') !== -1;
  };
  var nowNodes = nodes.filter(function(n) {
    var t = textOf(n);
    if (!t) return false;
    if (t.indexOf('예약') !== -1) return false;
    return t === '현재' || t.indexOf('현재 발행') !== -1 || t.indexOf('바로 발행') !== -1 || t.indexOf('즉시 발행') !== -1 || t.indexOf('지금 발행') !== -1;
  });
  for (var i=0; i<nowNodes.length; i++) {
    var n = nowNodes[i];
    var t = textOf(n);
    var target = n.closest('label,button') || n;
    if (isSelected(n) || isSelected(target)) return 'publish-now-already:' + t.substring(0,40);
    try { target.click(); } catch(e) { try { n.click(); } catch(e2) {} }
    return 'publish-now-selected:' + t.substring(0,40);
  }
  var radios = Array.from(document.querySelectorAll('input[type="radio"]'));
  for (var j=0; j<radios.length; j++) {
    var r = radios[j];
    var areaText = textOf(r.closest('label,li,div') || r);
    var v = String(r.value || r.id || r.name || '').toLowerCase();
    if ((areaText.indexOf('현재') !== -1 || v.indexOf('now') !== -1 || v.indexOf('immediate') !== -1) && areaText.indexOf('예약') === -1) {
      if (r.checked) return 'publish-now-radio-already:' + areaText.substring(0,40);
      try { r.click(); } catch(e3) {}
      return 'publish-now-radio-selected:' + areaText.substring(0,40);
    }
  }
  return 'DIAG:publish-now-option-not-found';
})()
"""
        PUBLIC_VISIBILITY_JS = """
return (function() {
  var nodes = Array.from(document.querySelectorAll('button,label,a,span,div,input'));
  var textOf = function(n) { return (n.innerText || n.textContent || n.getAttribute('aria-label') || n.getAttribute('title') || n.value || '').trim(); };
  var clsOf = function(n) { return typeof n.className === 'string' ? n.className : String(n.className || ''); };
  var isSelected = function(n) {
    return n.checked === true || n.getAttribute('aria-checked') === 'true' || clsOf(n).indexOf('checked') !== -1 || clsOf(n).indexOf('selected') !== -1 || clsOf(n).indexOf('active') !== -1;
  };
  var publicNodes = nodes.filter(function(n) {
    var t = textOf(n);
    if (!t) return false;
    if (t.indexOf('비공개') !== -1 || t.indexOf('이웃') !== -1 || t.indexOf('서로이웃') !== -1) return false;
    return t.indexOf('전체공개') !== -1 || t === '공개';
  });
  for (var i=0; i<publicNodes.length; i++) {
    var n = publicNodes[i];
    var t = textOf(n);
    var target = n.closest('label,button') || n;
    if (isSelected(n) || isSelected(target)) return 'public-already:' + t.substring(0,40);
    try { target.click(); } catch(e) { try { n.click(); } catch(e2) {} }
    return 'public-selected:' + t.substring(0,40);
  }
  var radios = Array.from(document.querySelectorAll('input[type="radio"]'));
  for (var j=0; j<radios.length; j++) {
    var r = radios[j];
    var v = String(r.value || r.id || r.name || '').toLowerCase();
    var areaText = textOf(r.closest('label,li,div') || r);
    if ((v.indexOf('public') !== -1 || areaText.indexOf('전체공개') !== -1) && areaText.indexOf('비공개') === -1) {
      if (r.checked) return 'public-radio-already:' + areaText.substring(0,40);
      try { r.click(); } catch(e3) {}
      return 'public-radio-selected:' + areaText.substring(0,40);
    }
  }
  return 'DIAG:public-option-not-found';
})()
"""
        CONFIRM_BTN_JS = """
return (function() {
  var allBtns = Array.from(document.querySelectorAll('button'));
  var getClass = function(b) { return typeof b.className === 'string' ? b.className : String(b.className || ''); };
  var getText  = function(b) { return (b.innerText || b.textContent || '').trim(); };
  var btn = allBtns.find(function(b) { return getClass(b).indexOf('confirm_btn') !== -1; });
  if (!btn) btn = allBtns.find(function(b){ return (getText(b)==='발행'||getText(b)==='발행하기') && getClass(b).indexOf('confirm')!==-1; });
  if (!btn) return null;
  try { btn.click(); } catch(e) { return 'confirm-err:'+String(e); }
  return getClass(btn).substring(0,50);
})()
"""
        def _exec_in_mainframe(js: str):
            """mainFrame 컨텍스트에서 JS를 실행. default → mainFrame 순으로 명시적 전환."""
            def _usable_result(value) -> bool:
                if not value:
                    return False
                text = str(value)
                return not (
                    text.startswith("DIAG:")
                    or text.startswith("click-err:")
                    or text.startswith("confirm-err:")
                )

            last_diag = None
            # 1. 먼저 default 시도
            try:
                self.driver.switch_to.default_content()
                r = self.driver.execute_script(js)
                if _usable_result(r):
                    self._log(f"[publish-dom] default ctx 성공: {r}")
                    return r
                if r:
                    last_diag = r
                    self._log(f"[publish-dom] default ctx 진단: {r}")
            except Exception as e:
                self._log(f"[publish-dom] default ctx 예외: {e}")
            # 2. mainFrame 으로 명시적 전환
            try:
                self.driver.switch_to.default_content()
                cur_url = self.driver.current_url
                self._log(f"[publish-dom] 현재 URL: {cur_url[:60]}")
                WebDriverWait(self.driver, 5).until(
                    EC.frame_to_be_available_and_switch_to_it((By.ID, "mainFrame"))
                )
                self._log("[publish-dom] mainFrame 전환 성공")
                r = self.driver.execute_script(js)
                if not r:
                    # 진단: 어떤 버튼이 있는지 확인
                    diag = self.driver.execute_script("""
return Array.from(document.querySelectorAll('button')).slice(0,10).map(b=>({
  cls:b.className.substring(0,50), text:(b.innerText||'').trim().substring(0,15), dis:b.disabled
}));
""")
                    self._log(f"[publish-dom] mainFrame 버튼 목록: {diag}")
                elif not _usable_result(r):
                    last_diag = r
                    self._log(f"[publish-dom] mainFrame 진단: {r}")
                else:
                    self._log(f"[publish-dom] mainFrame JS 결과: {r}")
                    return r
                self._log(f"[publish-dom] mainFrame JS 결과: {r}")
            except Exception as e:
                self._log(f"[publish-dom] mainFrame 전환/실행 예외: {e}")
            # 3. 모든 iframe 순회
            try:
                self.driver.switch_to.default_content()
                frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe")
                self._log(f"[publish-dom] iframe 수: {len(frames)}")
                for frame in frames:
                    try:
                        self.driver.switch_to.default_content()
                        self.driver.switch_to.frame(frame)
                        r = self.driver.execute_script(js)
                        if _usable_result(r):
                            self._log(f"[publish-dom] iframe 순회 성공: {r}")
                            return r
                        if r:
                            last_diag = r
                    except Exception:
                        continue
            except Exception as e:
                self._log(f"[publish-dom] iframe 순회 예외: {e}")
            if last_diag:
                self._log(f"[publish-dom] 성공 가능한 버튼 탐색 실패, 마지막 진단: {last_diag}")
            return None

        # Step 1: 발행 설정 패널 열기 (최대 3회 재시도)
        result1 = None
        for _i in range(3):
            result1 = _exec_in_mainframe(PUBLISH_BTN_JS)
            if result1:
                break
            self._log(f"발행 버튼 미발견 ({_i+1}/3), 팝업 닫기 재시도...")
            self._close_temporary_draft_list()
            time.sleep(1.5)
        if not result1:
            return False, "DOM 발행 버튼을 찾지 못했습니다 (publish_btn)"
        self._log(f"DOM 발행버튼 클릭 완료: {result1}")

        time.sleep(3)

        # Step 1.5: 발행 시점이 현재/즉시인지 명시적으로 선택/확인
        publish_now_result = _exec_in_mainframe(PUBLISH_NOW_JS)
        if publish_now_result:
            self._log(f"DOM 발행 시점 확인 완료: {publish_now_result}")
        else:
            self._log("DOM 발행 시점(현재/즉시) 옵션을 찾지 못했습니다. 기본값을 유지합니다.")
        time.sleep(1)

        # Step 1.6: 공개 범위가 전체공개인지 명시적으로 선택/확인
        visibility_result = _exec_in_mainframe(PUBLIC_VISIBILITY_JS)
        if not visibility_result:
            return False, "DOM 공개 설정(전체공개)을 확인하지 못했습니다."
        self._log(f"DOM 공개 설정 확인 완료: {visibility_result}")
        time.sleep(1)

        # Step 2: 발행 확정 버튼 클릭
        result2 = _exec_in_mainframe(CONFIRM_BTN_JS)
        if not result2:
            return False, "DOM 발행 확인 버튼을 찾지 못했습니다 (confirm_btn)"
        self._log(f"DOM 발행확인버튼 클릭 완료: {result2}")
        time.sleep(8)
        return True, f"DOM 발행 완료 (publish={result1}, publish_now={publish_now_result}, visibility={visibility_result}, confirm={result2})"

    def _publish_post(self) -> tuple[bool, str]:
        self._bring_chrome_to_front()
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

        # 임시저장 목록 팝업 닫기 (1회 - 저장 직후 남아 있을 수 있는 팝업)
        self._close_temporary_draft_list()

        x1, y1 = self.settings.publish_button1_x, self.settings.publish_button1_y
        x2, y2 = self.settings.publish_button2_x, self.settings.publish_button2_y
        delay = max(1, int(self.settings.publish_click_delay_seconds or 5))

        def _publish_post_via_coords(prefix_msg: str = "") -> tuple[bool, str]:
            if x1 <= 0 or y1 <= 0 or x2 <= 0 or y2 <= 0:
                return False, f"{prefix_msg}발행 버튼 좌표 미등록"

            original_failsafe = pyautogui.FAILSAFE
            try:
                pyautogui.FAILSAFE = False
                self._bring_chrome_to_front()
                pyautogui.moveTo(x1, y1, duration=0.35)
                time.sleep(0.15)
                pyautogui.click(x=x1, y=y1, duration=0.15)
                self._log(f"{prefix_msg}발행버튼1 클릭 완료: {x1}, {y1}")
                time.sleep(delay)
                pyautogui.moveTo(x2, y2, duration=0.35)
                time.sleep(0.15)
                pyautogui.click(x=x2, y=y2, duration=0.15)
                self._log(f"{prefix_msg}발행버튼2 클릭 완료: {x2}, {y2}")
                time.sleep(8)
                return True, f"{prefix_msg}발행버튼1/발행버튼2 클릭 완료"
            except Exception as exc:
                return False, f"{prefix_msg}발행 버튼 클릭 중 오류: {exc}"
            finally:
                pyautogui.FAILSAFE = original_failsafe

        force_coords = os.getenv("NEW_DSM_FORCE_COORD_PUBLISH", "").strip().lower() in {"1", "true", "yes"}
        if force_coords:
            coord_ok, coord_msg = _publish_post_via_coords("좌표 우선 ")
            if coord_ok:
                return coord_ok, coord_msg
            self._log(f"좌표 우선 발행 실패, DOM 발행으로 폴백: {coord_msg}")

        # 우선: DOM 기반 발행 (Chrome 창 위치/크기 무관)
        dom_ok, dom_msg = self._publish_post_via_dom()
        if dom_ok:
            return dom_ok, dom_msg
        self._log(f"DOM 발행 실패, PyAutoGUI 좌표 발행으로 폴백: {dom_msg}")

        coord_ok, coord_msg = _publish_post_via_coords("DOM 발행 실패 후 좌표 폴백 ")
        if coord_ok:
            return coord_ok, coord_msg
        return False, f"DOM 발행 실패({dom_msg}) + 좌표 발행 실패({coord_msg})"

    def _close_temporary_draft_list(self) -> None:
        """임시저장 목록 팝업을 닫는다.

        팝업은 mainFrame 내부에 존재하며 닫기/계속 쓰기/확인 버튼이 있다.
        버튼을 못 찾으면 Escape 키를 pyautogui로 직접 전송한다.
        """
        CLOSE_JS = """
(function() {
  // 팝업 컨테이너 탐색: dialog 역할, 레이어, 팝업 계열 클래스
  const candidates = Array.from(document.querySelectorAll(
    '[role="dialog"], [class*="popup"], [class*="layer"], [class*="modal"], [class*="dimmed"], [class*="temp_draft"]'
  ));
  // 임시저장 목록 팝업 텍스트 키워드
  const POPUP_KEYWORDS = ['임시저장 글', '임시저장한 글', '임시저장 목록', '총'];
  // 닫기용 버튼 텍스트 / aria 키워드
  const CLOSE_KWORDS = ['닫기', '계속 쓰기', '계속쓰기', '확인', 'Close', 'close'];
  for (const d of candidates) {
    const text = (d.innerText || d.textContent || '').trim();
    const hasPopup = POPUP_KEYWORDS.some(k => text.includes(k));
    if (!hasPopup) continue;
    const allBtns = Array.from(d.querySelectorAll('button, a, [role="button"]'));
    for (const kw of CLOSE_KWORDS) {
      const btn = allBtns.find(b => {
        const vals = [b.innerText, b.textContent, b.getAttribute('aria-label'), b.getAttribute('title'), b.className]
          .map(v => (v || '').toString().trim());
        return vals.some(v => v.includes(kw));
      });
      if (btn) { btn.click(); return 'clicked:' + kw; }
    }
    // 닫기 버튼이 없으면 아무 버튼이나 첫 번째 클릭
    if (allBtns.length) { allBtns[allBtns.length - 1].click(); return 'fallback-last-btn'; }
  }
  // 전체 body 에서 팝업 감지 (컨테이너가 특수 클래스가 아닌 경우)
  const body = (document.body ? document.body.innerText : '');
  if (POPUP_KEYWORDS.some(k => body.includes(k))) {
    const allBtns = Array.from(document.querySelectorAll('button, a[role="button"]'));
    for (const kw of CLOSE_KWORDS) {
      const btn = allBtns.find(b => {
        const vals = [b.innerText, b.textContent, b.getAttribute('aria-label')]
          .map(v => (v || '').trim());
        return vals.some(v => v.includes(kw));
      });
      if (btn) { btn.click(); return 'body-clicked:' + kw; }
    }
  }
  return null;
})()
"""
        def _attempt():
            try:
                result = self.driver.execute_script(CLOSE_JS)
                return result  # truthy 문자열이면 성공
            except Exception:
                return None

        found = False
        try:
            results = self._run_in_contexts(_attempt)
            found = any(r for r in results if r)
            if found:
                self._log(f"임시저장 목록 팝업 닫기 성공: {[r for r in results if r]}")
                time.sleep(1.5)
                return
        except Exception:
            pass

        # 팝업이 DOM에서 감지된 경우에만 pyautogui Escape 전송 (불필요한 Escape 방지)
        # body text 기반으로 팝업 존재 여부 한 번 더 확인
        popup_visible = False
        try:
            def _check_body():
                try:
                    body = self.driver.execute_script(
                        "return (document.body ? document.body.innerText : '') || '';"
                    ) or ""
                    return any(kw in body for kw in ["임시저장 글", "임시저장한 글", "총", "임시저장 목록"])
                except Exception:
                    return False
            popup_results = self._run_in_contexts(_check_body)
            popup_visible = any(popup_results)
        except Exception:
            pass

        if popup_visible:
            try:
                pyautogui.press('escape')
                time.sleep(1.0)
                self._log("임시저장 목록 팝업: pyautogui Escape 전송")
            except Exception:
                pass
        # 팝업이 없는 경우엔 Escape를 보내지 않음 (에디터 상태 보호)

    def test_publish_buttons(self) -> tuple[bool, str]:
        ok, msg = self.connect()
        if not ok:
            return False, msg
        return self._publish_post()

    def test_login_only(self, force_input: bool = False) -> tuple[bool, str]:
        self.wait_for_manual_challenge = False
        self._log("로그인 단독 테스트: Chrome 연결 중...")
        ok, msg = self.connect()
        if not ok:
            return False, msg
        self._log("로그인 단독 테스트: 네이버 메인 기반 로그인 경로 시작")
        try:
            self.driver.get(NAVER_HOME_URL)
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception as exc:
            return False, f"네이버 메인 이동 실패: {exc}"
        if self._has_naver_session() and not force_input:
            return True, "로그인 테스트 성공: 이미 로그인 세션이 있습니다."
        self._log("로그인 단독 테스트: 네이버 메인 로그인 버튼/저장 입력 우선 시도")
        ok, msg = self._attempt_auto_login(force_input=force_input)
        if ok:
            return True, f"로그인 테스트 성공: {msg}"
        return False, f"로그인 테스트 실패: {msg}"

    # ─── 메인 진입점 ───────────────────────────────────────────────────────

    def insert_draft_content_only(
        self,
        title: str,
        body: str,
        cta: str,
        image_paths: list[Path] | None = None,
        log_callback=None,
    ) -> tuple[bool, str]:
        """Open Smart Editor and insert title/body/images without saving.

        Used by DSM repertoire insertion tests where the user wants to inspect
        the editor before draft save. This must not call _save_draft().
        """
        if log_callback:
            self.log_callback = log_callback

        image_map: dict[str, Path] = {}
        if image_paths and (IMAGES_FIRST_MODE or not TEXT_ONLY_MODE or INSERT_IMAGES_AFTER_TEXT or SEGMENTED_IMAGE_MODE):
            image_map = {f"photo_{idx:02d}.jpg": path for idx, path in enumerate(image_paths, start=1)}

        self._log("Chrome 연결 중...")
        ok, msg = self.connect()
        if not ok:
            return False, msg

        self._log("로그인 확인 중...")
        ok, msg = self._ensure_logged_in()
        if not ok:
            return False, f"네이버 로그인이 필요합니다. 초기 등록 탭에서 로그인하거나 자동 로그인 설정을 확인해주세요. ({msg})"
        self._log(msg)

        self._log("새 글쓰기 탭 열기...")
        ok, detail = self._open_editor_in_new_tab()
        if not ok:
            return False, f"글쓰기 창을 열지 못했습니다: {detail}"
        self._handle_popups()
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        time.sleep(1.0)
        self._bring_chrome_to_front()
        time.sleep(0.5)

        self._log("제목 입력 중...")
        self._handle_popups()
        editor_ready = self._ensure_editor_ready()
        if not editor_ready:
            return False, "에디터가 준비되지 않았습니다. 네이버 글쓰기 창을 확인해주세요."
        self._type_title(title)
        title_ok, title_actual = self._ensure_title_written(title)
        if not title_ok:
            return False, f"제목 입력 확인 실패: 에디터 읽힌 값='{title_actual}'"
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        time.sleep(0.4)

        self._log("본문/사진 입력 중...")
        if not IMAGES_FIRST_MODE and not SEGMENTED_IMAGE_MODE:
            self._ensure_editor_ready()
            self._focus_body()
        body_ok, body_msg = self._insert_body(body, image_map)
        if not body_ok:
            return False, f"본문 입력 실패: {body_msg}"
        self._log(body_msg)
        verified, body_actual = self._verify_body_written(body)
        if not verified:
            return False, f"본문 입력 확인 실패: 네이버 글쓰기 창에 본문이 감지되지 않았습니다. 감지값={body_actual}"

        if image_map and INSERT_IMAGES_AFTER_TEXT:
            self._log("사진 자리표시자 치환 중...")
            images_ok, images_msg = self._insert_images_after_text(image_map)
            if not images_ok:
                return False, images_msg
            self._log(images_msg)

        if cta.strip() and INSERT_SEPARATE_CTA:
            self._log("CTA 입력 중...")
            self._ensure_editor_ready()
            self._focus_body()
            ActionChains(self.driver).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
            time.sleep(0.2)
            self._type_body_text(cta)

        return True, "제목/본문/이미지 삽입 완료 - 임시저장/발행은 수행하지 않았습니다."

    def publish_draft(
        self,
        title: str,
        body: str,
        cta: str,
        image_paths: list[Path] | None = None,
        publish_after_save: bool = False,
        log_callback=None,
    ) -> tuple[bool, str]:
        if log_callback:
            self.log_callback = log_callback

        image_map: dict[str, Path] = {}
        if image_paths and (IMAGES_FIRST_MODE or not TEXT_ONLY_MODE or INSERT_IMAGES_AFTER_TEXT or SEGMENTED_IMAGE_MODE):
            image_map = {f"photo_{idx:02d}.jpg": path for idx, path in enumerate(image_paths, start=1)}

        # CONNECT
        self._log("Chrome 연결 중...")
        ok, msg = self.connect()
        if not ok:
            return False, msg

        # LOGIN CHECK
        self._log("로그인 확인 중...")
        ok, msg = self._ensure_logged_in()
        if not ok:
            return False, f"네이버 로그인이 필요합니다. 초기 등록 탭에서 로그인하거나 자동 로그인 설정을 확인해주세요. ({msg})"
        self._log(msg)

        # OPEN EDITOR
        self._log("글쓰기 창 열기...")
        ok, detail = self._open_editor()
        if not ok:
            return False, f"글쓰기 창을 열지 못했습니다: {detail}"
        # 팝업 처리 후 default 컨텍스트로 복귀
        self._handle_popups()
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        time.sleep(1.0)
        self._bring_chrome_to_front()
        time.sleep(0.5)

        # TYPE TITLE — 에디터 DOM이 있는 컨텍스트로 이동 후 입력
        self._log("제목 입력 중...")
        self._handle_popups()
        editor_ready = self._ensure_editor_ready()
        if not editor_ready:
            return False, "에디터가 준비되지 않았습니다. 네이버 글쓰기 창을 확인해주세요."
        self._type_title(title)
        title_ok, title_actual = self._ensure_title_written(title)
        if not title_ok:
            return False, f"제목 입력 확인 실패: 에디터 읽힌 값='{title_actual}'"
        # 제목 → 본문 영역 이동 (항상 ENTER)
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        time.sleep(0.4)

        # TYPE BODY — IMAGES_FIRST_MODE / SEGMENTED_IMAGE_MODE는 내부에서 포커스 관리
        self._log("본문/사진 입력 중...")
        if not IMAGES_FIRST_MODE and not SEGMENTED_IMAGE_MODE:
            self._ensure_editor_ready()
            self._focus_body()
        body_ok, body_msg = self._insert_body(body, image_map)
        if not body_ok:
            return False, f"본문 입력 실패: {body_msg}"
        self._log(body_msg)
        verified, body_actual = self._verify_body_written(body)
        if not verified:
            return False, f"본문 입력 확인 실패: 네이버 글쓰기 창에 본문이 감지되지 않아 임시저장을 중단했습니다. 감지값={body_actual}"

        if image_map and INSERT_IMAGES_AFTER_TEXT:
            self._log("사진 자리표시자 치환 중...")
            images_ok, images_msg = self._insert_images_after_text(image_map)
            if not images_ok:
                return False, images_msg
            self._log(images_msg)

        # TYPE CTA
        if cta.strip() and INSERT_SEPARATE_CTA:
            self._log("CTA 입력 중...")
            self._ensure_editor_ready()
            self._focus_body()
            ActionChains(self.driver).send_keys(Keys.ENTER).send_keys(Keys.ENTER).perform()
            time.sleep(0.2)
            self._type_body_text(cta)

        # PUBLISH or SAVE DRAFT
        self._strip_stray_bold()

        if publish_after_save:
            # 임시저장 없이 직접 발행 (저장 팝업이 에디터 DOM을 변경하는 문제 회피)
            self._log("발행 진행 중 (직접 발행 모드)...")
            published, publish_msg = self._publish_post()
            if published:
                return True, publish_msg
            # 직접 발행 실패 → 저장 후 재시도
            self._log(f"직접 발행 실패 ({publish_msg}), 임시저장 후 재시도...")
            ok, msg = self._save_draft()
            if not ok:
                return ok, msg
            time.sleep(2)
            self._close_temporary_draft_list()
            time.sleep(1)
            published, publish_msg = self._publish_post()
            if not published:
                return False, publish_msg
            return True, f"{msg} / {publish_msg}"
        else:
            self._log("임시저장 중...")
            ok, msg = self._save_draft()
            if not ok:
                return ok, msg
            return ok, msg

    def get_current_draft_url(self) -> str:
        """임시저장 직후 현재 글쓰기 창 주소(blogId/logNo 형태) 반환 — 텔레그램으로
        임시저장 링크를 바로 보내주기 위함(2026-07-02). 실패 시 빈 문자열."""
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        try:
            return self.driver.current_url or ""
        except Exception:
            return ""

    def get_published_url(self) -> str:
        """발행 직후 공개 글 URL을 확보(logNo 추출). 실패 시 블로그 홈 URL."""
        blog_id = (self.settings.naver_id or "").strip()
        urls = []
        try:
            self.driver.switch_to.default_content()
            urls.append(self.driver.current_url or "")
        except Exception:
            pass
        try:
            self._switch_to_editor_frame()
            urls.append(self.driver.current_url or "")
        except Exception:
            pass
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        for u in urls:
            m = re.search(r"logNo=(\d+)", u) or re.search(r"blog\.naver\.com/[^/?#]+/(\d{6,})", u)
            if m:
                return f"https://blog.naver.com/{blog_id}/{m.group(1)}"
        return f"https://blog.naver.com/{blog_id}" if blog_id else ""

    def quit(self) -> None:
        """attach(debuggerAddress) 방식이므로 사용자 크롬을 닫지 않는다(닫으면 로그인 세션 유실).
        드라이버 참조만 해제하고 브라우저는 그대로 둔다."""
        self.driver = None
