#!/usr/bin/env python3
from __future__ import annotations
import json, sys
request=json.load(sys.stdin)
command=str(request.get('command',''))
if 'review-error' in command:
    print('simulated reviewer failure', file=sys.stderr)
    raise SystemExit(2)
if 'opaque-risk' in command or 'os.remove' in command or 'socket.connect' in command:
    result={
        'risk':'high',
        'categories':['destructive-or-network-side-effect'],
        'reason':'The command uses general-purpose code execution to perform a consequential side effect that static command-name rules do not expose.',
        'confidence':0.91,
        'reviewer':'fake-semantic-reviewer'
    }
else:
    # Deliberately returns none for known deterministic risks to prove that the
    # semantic layer cannot downgrade static findings.
    result={'risk':'none','categories':[],'reason':'No additional semantic-only risk found.','confidence':0.8,'reviewer':'fake-semantic-reviewer'}
print(json.dumps(result))
