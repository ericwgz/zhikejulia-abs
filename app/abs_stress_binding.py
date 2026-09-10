"""Bind exact copied display quantities; never guess, round or infer values."""
from decimal import Decimal, InvalidOperation
import re


TOKEN = re.compile(r'\{\{[^{}]*\}\}')
DATE = re.compile(r'(?<![A-Za-z0-9_./-])\d{4}-\d{2}-\d{2}(?![A-Za-z0-9_./-])')
NUMBER = r'[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?'
UNITS = r'个百分点|万元|个月|元|[%％]|倍|×|分|期|月|天|项|年'
QUANTITY = re.compile(r'(?<![A-Za-z0-9_.,+\-−－＋])(' + NUMBER + r')[ \t]*(' + UNITS + r')(?![A-Za-z0-9_./%％×])')
DISPLAY = re.compile(r'^(' + NUMBER + r')[ \t]*(' + UNITS + r')$')
EXPRESSION_PREFIX = re.compile(r'(?:[<>=!]=?|[≤≥])\s*$')
UNIT_ALIASES = {'％': '%', '×': '倍', '月': '个月'}


def _quantity_key(value):
    match = DISPLAY.fullmatch(value.strip())
    if not match:
        return None
    try:
        number = Decimal(match[1].replace(',', ''))
    except InvalidOperation:
        return None
    # Use displayed values, not hidden extra precision in the original calculation.
    return number, UNIT_ALIASES.get(match[2], match[2])


def normalize(text, bindings, cited_refs):
    """Replace only exact quantities owned by this paragraph's cited evidence.

    Existing tokens and non-date source literals are opaque. Unit aliases do not
    change scale: yuan and ten-thousand-yuan values remain distinct. Conditions
    are never used as quantity bindings; callers must not apply this to triggers.
    """
    if not isinstance(text, str):
        return text
    cited = set(cited_refs)
    quantities, dates, protected_literals = {}, {}, []
    for key in sorted(bindings):
        binding = bindings[key]
        shown = binding.get('text')
        if not isinstance(shown, str):
            continue
        kind = binding.get('kind')
        if kind == 'literal':
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', shown):
                if binding.get('ref') in cited:
                    dates.setdefault(shown, key)
            elif shown:
                protected_literals.append(shown)
            continue
        if kind == 'condition' or binding.get('ref') not in cited:
            continue
        parsed = _quantity_key(shown)
        if parsed is not None:
            quantities.setdefault(parsed, key)

    # Do not interpret any existing token or literal filename as free prose.
    alternatives = [TOKEN.pattern] + [re.escape(s) for s in sorted(set(protected_literals), key=lambda s: (-len(s), s))]
    protected = re.compile('|'.join(alternatives))

    def free_prose(segment):
        def copied_date(match):
            key = dates.get(match[0])
            return '{{' + key + '}}' if key is not None else match[0]

        def copied_quantity(match):
            # An expression's operator cannot be normalized into a new condition.
            if EXPRESSION_PREFIX.search(segment[:match.start()]):
                return match[0]
            key = quantities.get(_quantity_key(match[0]))
            return '{{' + key + '}}' if key is not None else match[0]

        # Dates are not quantity strings. Both passes preserve unsupported text.
        segment = QUANTITY.sub(copied_quantity, segment)
        return DATE.sub(copied_date, segment)

    chunks, cursor = [], 0
    for match in protected.finditer(text):
        chunks.append(free_prose(text[cursor:match.start()]))
        chunks.append(match[0])
        cursor = match.end()
    chunks.append(free_prose(text[cursor:]))
    return ''.join(chunks)
