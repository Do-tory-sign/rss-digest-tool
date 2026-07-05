import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
from news.curator import _call_gemini

p = Path('D:/Dotory/Cardnews/output/20260607/curated.json')
data = json.loads(p.read_text(encoding='utf-8'))

hot = data['hot']['card_headline']
eco = data['economy']['card_headline']
trd = data['culture']['card_headline']

prompt = (
    "아래 뉴스 제목 3개를 각각 20자 이내로 임팩트 있게 요약하세요.\n"
    "원제목에 있는 사실만 사용하고, 이모지 없이, JSON으로만 응답하세요.\n\n"
    f"HOT 원제목: {hot}\n"
    f"ECO 원제목: {eco}\n"
    f"TRD 원제목: {trd}\n\n"
    '{"hot": "20자 이내 요약", "eco": "20자 이내 요약", "trd": "20자 이내 요약"}'
)

result = _call_gemini(prompt)
print('HOT:', result.get('hot'))
print('ECO:', result.get('eco'))
print('TRD:', result.get('trd'))

data['hot']['cover_headline'] = result.get('hot') or hot
data['economy']['cover_headline'] = result.get('eco') or eco
data['culture']['cover_headline'] = result.get('trd') or trd
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('저장 완료')
