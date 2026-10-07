import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from pathlib import Path
import re
from html import escape
from scripts.data_seed import PRODUCTS

OUT=Path('app/static/img/products'); OUT.mkdir(parents=True,exist_ok=True)
PALETTES={
 'Бакалея, крупы, мука':('#EDE5D2','#7B5E30','#F8F4EA'),
 'Масла и соусы':('#F1E4C7','#9A5A1D','#FBF6E9'),
 'Молочные продукты и сыры':('#E7EEF2','#47697A','#F7FBFC'),
 'Заморозка, мясо и полуфабрикаты':('#EDE7E5','#7F4B3C','#FAF6F4'),
 'Рыба и морепродукты':('#DDECF1','#2D7181','#F4FAFB'),
 'Консервация и пасты':('#E8E7DA','#657043','#F7F8F0'),
 'Напитки, морсы и сиропы':('#E9E1EF','#6A4B7D','#FAF7FC'),
 'Десерты и выпечка (заказ)':('#F2E0DF','#8B4C57','#FFF8F8'),
}

def slug(s): return re.sub(r'[^a-z0-9а-яё]+','-',s.lower()).strip('-')

def initials(name):
    words=[w for w in re.split(r'\s+',name.strip()) if w]
    if not words: return '•'
    if len(words)==1: return words[0][:2].upper()
    return (words[0][0]+words[1][0]).upper()

def icon_for(cat):
    if cat=='Бакалея, крупы, мука': return '<path d="M122 130h156l-18 135H140z" fill="none" stroke="{ink}" stroke-width="9" rx="12"/><path d="M150 130v-20c0-22 18-40 40-40h20c22 0 40 18 40 40v20" fill="none" stroke="{ink}" stroke-width="9"/>'
    if cat=='Масла и соусы': return '<rect x="140" y="90" width="120" height="190" rx="24" fill="none" stroke="{ink}" stroke-width="9"/><rect x="165" y="70" width="70" height="25" rx="9" fill="none" stroke="{ink}" stroke-width="9"/><path d="M160 170h80" stroke="{ink}" stroke-width="9"/>'
    if cat=='Молочные продукты и сыры': return '<path d="M125 105h150v150H125z" fill="none" stroke="{ink}" stroke-width="9" rx="16"/><path d="M125 125h150" stroke="{ink}" stroke-width="9"/><circle cx="175" cy="190" r="24" fill="none" stroke="{ink}" stroke-width="8"/>'
    if cat=='Заморозка, мясо и полуфабрикаты': return '<path d="M120 120c38-35 162-35 200 0v120c-38 34-162 34-200 0z" fill="none" stroke="{ink}" stroke-width="9"/><path d="M155 150c40 20 90 20 130 0M155 205c40-20 90-20 130 0" fill="none" stroke="{ink}" stroke-width="8"/>'
    if cat=='Рыба и морепродукты': return '<path d="M110 195c55-70 135-78 195-15l40-30v90l-40-30c-60 63-140 55-195-15z" fill="none" stroke="{ink}" stroke-width="9"/><circle cx="205" cy="180" r="8" fill="{ink}"/>'
    if cat=='Консервация и пасты': return '<rect x="130" y="95" width="140" height="175" rx="28" fill="none" stroke="{ink}" stroke-width="9"/><path d="M150 95h100M155 175h90" stroke="{ink}" stroke-width="9"/>'
    if cat=='Напитки, морсы и сиропы': return '<path d="M145 110h110l-12 160h-86z" fill="none" stroke="{ink}" stroke-width="9"/><path d="M165 85h70" stroke="{ink}" stroke-width="14"/><path d="M165 155c25 20 50-15 75 5" fill="none" stroke="{ink}" stroke-width="8"/>'
    return '<circle cx="200" cy="185" r="92" fill="none" stroke="{ink}" stroke-width="9"/><path d="M135 205c40-75 90-75 130 0M145 235c35-25 75-25 110 0" fill="none" stroke="{ink}" stroke-width="8"/>'

for cat,name in PRODUCTS:
    bg,ink,paper=PALETTES[cat]
    esc=escape(name)
    ini=escape(initials(name))
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="680" viewBox="0 0 400 340">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{bg}"/><stop offset="1" stop-color="{paper}"/></linearGradient></defs>
<rect width="400" height="340" rx="28" fill="url(#g)"/><circle cx="320" cy="70" r="62" fill="rgba(255,255,255,.38)"/>
<g fill="none">{icon_for(cat).format(ink=ink)}</g>
<circle cx="320" cy="70" r="42" fill="#fff" opacity=".78"/><text x="320" y="79" text-anchor="middle" font-family="Arial,sans-serif" font-size="28" font-weight="800" fill="{ink}">{ini}</text>
<rect x="28" y="288" width="344" height="2" fill="{ink}" opacity=".18"/><text x="30" y="316" font-family="Arial,sans-serif" font-size="13" font-weight="700" fill="{ink}">{esc[:52]}</text>
</svg>'''
    (OUT/(slug(name)+'.svg')).write_text(svg,encoding='utf-8')
(OUT/'placeholder.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="340"><rect width="400" height="340" rx="28" fill="#ededeb"/><path d="M160 220l45-55 35 42 25-30 55 43z" fill="none" stroke="#999" stroke-width="8"/><circle cx="190" cy="130" r="20" fill="none" stroke="#999" stroke-width="8"/></svg>',encoding='utf-8')
print('generated',len(PRODUCTS),'images')
