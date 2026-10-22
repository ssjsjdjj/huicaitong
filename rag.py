"""Dependency-free BM25 with Chinese unigram/bigram lexical segmentation."""
import math
import hashlib
import json
import re
from collections import Counter
from datetime import date
from policy_time import available


def tokenize(text):
    terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower())
    tokens = []
    for term in terms:
        if re.fullmatch(r"[\u4e00-\u9fff]+", term):
            tokens.extend(term)
            tokens.extend(term[i:i+2] for i in range(len(term)-1))
        else:
            tokens.append(term)
    return tokens


def retrieve(policies, query, as_of="2026-10-21", limit=6, include_archived=False):
    if not isinstance(query, str) or len(query) > 4000:
        raise ValueError("检索问题须为不超过 4000 字的文本")
    if not isinstance(as_of,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",as_of):
        raise ValueError("检索参考日期须为 YYYY-MM-DD")
    date.fromisoformat(as_of)
    docs = []
    for p in policies:
        if not available(p, as_of, historical=include_archived):
            continue
        for clause in p["clauses"]:
            docs.append({**clause, "policy_id":p["id"], "policy_title":p["title"], "published_on":p["published_on"], "status":p["status"], "outside_reference_period":not available(p,as_of),"source_url":p["source_url"], "source_org":p["source_org"], "text_tokens":tokenize(p["title"] + " " + clause["section"] + " " + clause["text"])})
    if not docs or not query.strip():
        return []
    query_terms = set(tokenize(query))
    frequencies = Counter()
    for d in docs:
        frequencies.update(set(d["text_tokens"]))
    average_length = sum(len(d["text_tokens"]) for d in docs) / len(docs)
    for d in docs:
        counts = Counter(d.pop("text_tokens"))
        length = sum(counts.values())
        score = 0
        for term in query_terms:
            if term not in counts:
                continue
            idf = math.log(1 + (len(docs) - frequencies[term] + .5) / (frequencies[term] + .5))
            tf = counts[term]
            score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / average_length))
        d["score"] = round(score, 4)
    return sorted([d for d in docs if d["score"] > 0], key=lambda x: (-x["score"], x["id"]))[:max(1,min(limit,12))]


def evidence_context(policy, profile, question=None):
    """Rank the selected matter, then expand all rule/material-linked clauses.

    Top-k alone cannot establish eligibility: omitted exclusions can reverse a
    verdict. Coverage here is relative to the encoded rules, not the full law.
    """
    if not available(policy, profile["application_date"]):
        raise ValueError("该事项在参考日期不可用于当前核验")
    if question is not None and (not isinstance(question,str) or len(question)>2000):
        raise ValueError("核验问题须为不超过 2000 字的文本")
    query=(question or "").strip() or policy["title"]+" 申请条件 参保 排除条件 准备信息"
    hits=retrieve([policy],query,profile["application_date"],limit=3)
    required={r["citation"] for key in ("scope","rules","materials") for r in policy[key]}
    clauses={c["id"]:c for c in policy["clauses"]}
    if not required <= clauses.keys():
        raise ValueError("政策存在未绑定的必要证据，暂停模型核验")
    hit_ids=[h["id"] for h in hits]
    expanded=[c["id"] for c in policy["clauses"] if c["id"] in required and c["id"] not in hit_ids]
    ordered=hit_ids+expanded
    context=[clauses[i] for i in ordered]
    return {"clauses":context,"trace":{
        "method":"bm25-required-v1", "query":query, "policy_id":policy["id"],
        "as_of":profile["application_date"], "published_on":policy["published_on"],
        "hits":[{"id":h["id"],"section":h["section"],"score":h["score"]} for h in hits],
        "expanded_ids":expanded, "context_ids":ordered,
        "required_ids":sorted(required),"encoded_rule_coverage_complete":True,
        "policy_sha256":hashlib.sha256(json.dumps(policy,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "context_sha256":hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "notice":"在所选事项内检索，再补齐已录入规则和准备清单关联的条款。覆盖完整仅指已录入规则，不证明原政策完整或现行有效；没有使用向量检索。",
    }}
