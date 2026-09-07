"""Embed audited historical data in the inline figure; never run a new search."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
VISUAL = HERE / 'visualization.html'
source = json.loads((HERE / 'data.json').read_text(encoding='utf-8'))
rows = [{**{k: row[k] for k in ('move', 'san', 'preceding_black_san')},
         'numeric_pawns': row['score_pawns'], 'depth': row['completed_depth']}
        for row in source['rows']]
fragment = VISUAL.read_text(encoding='utf-8')
data = json.dumps({'rows': rows}, ensure_ascii=False)
fragment, count = re.subn(r'(<script id="wally-eval-data" type="application/json">).*?(</script>)',
                          lambda m: m[1] + data + m[2], fragment, flags=re.S)
assert count == 1, 'Expected one embedded data element'
VISUAL.write_text(fragment, encoding='utf-8')
assert len(rows) == 31 and sum(r['numeric_pawns'] is not None for r in rows) == 28
print('Embedded 28 numerical estimates and 3 mate outcomes.')
