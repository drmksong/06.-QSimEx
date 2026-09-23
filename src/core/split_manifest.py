"""Utilities to create Train/Validation manifests by DFN seed/domain.

Functions are intentionally small and dependency-light so they can be
used from CLI wrappers or unit tests without heavy imports.
"""
from typing import List, Dict, Any, Tuple, Optional
import json
import random


def split_cases_by_domain(
    cases: List[Dict[str, Any]],
    domain_key: str = "domain",
    train_frac: float = 0.7,
    random_state: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split a list of case dicts into Train/Validation by domain grouping.

    - cases: iterable of dict-like objects. Each case must contain `domain_key`.
    - Returns: (train_cases, validation_cases)

    The split is performed on the set of unique domain identifiers so that all
    cases from the same domain are assigned to the same split.
    """
    if random_state is not None:
        random.seed(random_state)

    # Group case indices by domain
    domain_to_cases: Dict[Any, List[Dict[str, Any]]] = {}
    for c in cases:
        if domain_key not in c:
            raise KeyError(f"domain key '{domain_key}' missing in case: {c}")
        d = c[domain_key]
        domain_to_cases.setdefault(d, []).append(c)

    domains = list(domain_to_cases.keys())
    random.shuffle(domains)

    n_train_domains = max(1, int(len(domains) * float(train_frac)))
    train_domains = set(domains[:n_train_domains])

    train_cases: List[Dict[str, Any]] = []
    validation_cases: List[Dict[str, Any]] = []

    for dom, cs in domain_to_cases.items():
        if dom in train_domains:
            train_cases.extend(cs)
        else:
            validation_cases.extend(cs)

    return train_cases, validation_cases


def build_manifest(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Construct a simple manifest summarizing domains and counts.

    Manifest format example:
    {
      "n_cases": 480,
      "domains": {"domainA": 10, "domainB": 20},
    }
    """
    domains: Dict[Any, int] = {}
    for c in cases:
        d = c.get("domain")
        domains[d] = domains.get(d, 0) + 1

    return {"n_cases": len(cases), "domains": domains}


def write_manifest(manifest: Dict[str, Any], path: str) -> None:
    """Write the manifest dict as JSON to `path`."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)


__all__ = ["split_cases_by_domain", "build_manifest", "write_manifest"]
