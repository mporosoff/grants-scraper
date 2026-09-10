"""Independent exhaustive finite-pool coverage reference, stdin/stdout only."""
import itertools
import json
import sys
import math

def evaluate(case):
    weights,rows=case['weights'],case['rows']
    def score(ids): return sum(w*max((rows[j]['scores'][i] for j in ids),default=0) for i,w in enumerate(weights))
    feasible=[]
    for size in range(2,min(4,len(rows))+1):
        for ids in itertools.combinations(range(len(rows)),size):
            value=score(ids)
            if math.floor(value*1e6+.5)<550000 or not any(rows[j]['anchor'] for j in ids):continue
            if any(math.floor((value-score([k for k in ids if k!=j]))*1e6+.5)<30000 for j in ids):continue
            feasible.append({'ids':[rows[j]['id'] for j in ids],'score':value})
    return {'maximum':max((x['score'] for x in feasible),default=0),'count':len(feasible)}

if __name__=='__main__':print(json.dumps([evaluate(c) for c in json.load(sys.stdin)]))
