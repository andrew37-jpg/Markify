from html import escape
import re

PALETTES = {
    'Бакалея, крупы, мука': ('#EDE5D2', '#7B5E30', 'bag'),
    'Масла и соусы': ('#F1E4C7', '#9A5A1D', 'bottle'),
    'Молочные продукты и сыры': ('#E7EEF2', '#47697A', 'dairy'),
    'Заморозка, мясо и полуфабрикаты': ('#EDE7E5', '#7F4B3C', 'meat'),
    'Рыба и морепродукты': ('#DDECF1', '#2D7181', 'fish'),
    'Консервация и пасты': ('#E8E7DA', '#657043', 'jar'),
    'Напитки, морсы и сиропы': ('#E9E1EF', '#6A4B7D', 'drink'),
    'Десерты и выпечка (заказ)': ('#F2E0DF', '#8B4C57', 'dessert'),
}


def initials(name: str) -> str:
    words = [w for w in re.split(r'\s+', name.strip()) if w]
    if not words:
        return 'MK'
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def icon_body(kind: str, ink: str) -> str:
    common = f'fill="none" stroke="{ink}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"'
    return {
        'bag': f'<path d="M110 150h180l-22 125H132z" {common}/><path d="M150 150v-25c0-25 20-45 45-45h10c25 0 45 20 45 45v25" {common}/><circle cx="175" cy="205" r="7" fill="{ink}"/><circle cx="225" cy="205" r="7" fill="{ink}"/>',
        'bottle': f'<rect x="145" y="90" width="110" height="188" rx="25" {common}/><path d="M168 90V68h64v22" {common}/><path d="M164 168h72" {common}/>',
        'dairy': f'<path d="M125 112h150v165H125z" {common}/><path d="M125 135h150" {common}/><circle cx="176" cy="201" r="22" {common}/>',
        'meat': f'<path d="M110 145c44-38 136-38 180 0v112c-44 36-136 36-180 0z" {common}/><path d="M146 171c30 18 78 18 108 0M146 226c30-18 78-18 108 0" {common}/>',
        'fish': f'<path d="M95 205c58-74 139-82 201-20l28-24v88l-28-24c-62 62-143 54-201-20z" {common}/><circle cx="204" cy="185" r="8" fill="{ink}"/>',
        'jar': f'<rect x="128" y="92" width="144" height="184" rx="26" {common}/><path d="M145 112h110" {common}/><path d="M150 180h100" {common}/>',
        'drink': f'<path d="M145 105h110l-12 171h-86z" {common}/><path d="M167 82h66" {common}/><path d="M166 157c24 18 52-18 77 3" {common}/>',
        'dessert': f'<circle cx="200" cy="190" r="86" {common}/><path d="M138 215c38-64 84-64 124 0M148 241c33-23 71-23 104 0" {common}/>',
    }.get(kind, '')


def product_icon_svg(name: str, category: str) -> str:
    bg, ink, kind = PALETTES.get(category, ('#ECECE7', '#66665E', 'jar'))
    initials_text = escape(initials(name))
    safe_name = escape(name[:58])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="680" viewBox="0 0 400 340" role="img" aria-label="{escape(name)}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{bg}"/><stop offset="1" stop-color="#FCFCF8"/></linearGradient></defs>
<rect width="400" height="340" rx="28" fill="url(#g)"/>
<circle cx="318" cy="70" r="60" fill="#ffffff" opacity=".38"/>
<g>{icon_body(kind, ink)}</g>
<circle cx="318" cy="70" r="42" fill="#fff" opacity=".84"/>
<text x="318" y="79" text-anchor="middle" font-family="Arial,sans-serif" font-size="27" font-weight="800" fill="{ink}">{initials_text}</text>
<rect x="28" y="288" width="344" height="2" fill="{ink}" opacity=".18"/>
<text x="30" y="317" font-family="Arial,sans-serif" font-size="12" font-weight="700" fill="{ink}">{safe_name}</text>
</svg>'''
