"""Utilities to create Train/Validation manifests by DFN seed/domain.

Functions are intentionally small and dependency-light so they can be
used from CLI wrappers or unit tests without heavy imports.
"""
from typing import List, Dict, Any, Tuple, Optional, Iterable
import json
import random
import hashlib


def _normalize_feature(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {str(k): _normalize_feature(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_feature(v) for v in value]
    return value


def generation_signature(case: Dict[str, Any]) -> Dict[str, Any]:
    """Create a compact fingerprint describing the associated DFN generation inputs.

    This is deliberately simple and avoids depending on the full DFN runtime:
    it summarizes the primary parameters that determine a distinct DFN sample.
    """
    joint_sets = case.get("joint_sets", [])
    global_params = case.get("global_params", {}) or {}
    seed = case.get("seed")

    normalized_sets = []
    for js in joint_sets:
        normalized_sets.append({
            "set_id": js.get("set_id"),
            "mean_dip": _normalize_feature(js.get("mean_dip")),
            "mean_dip_dir": _normalize_feature(js.get("mean_dip_dir")),
            "fisher_kappa": _normalize_feature(js.get("fisher_kappa")),
            "size_alpha": _normalize_feature(js.get("size_alpha")),
            "size_r_min": _normalize_feature(js.get("size_r_min")),
            "size_r_max": _normalize_feature(js.get("size_r_max")),
            "density_type": js.get("density_type"),
            "P32": _normalize_feature(js.get("P32")),
            "mean_spacing": _normalize_feature(js.get("mean_spacing")),
        })

    return {
        "seed": seed,
        "joint_sets": sorted(normalized_sets, key=lambda x: str(x.get("set_id"))),
        "global_params": {
            "Jw_mean": _normalize_feature(global_params.get("Jw_mean")),
            "Jw_std": _normalize_feature(global_params.get("Jw_std")),
            "SRF_mean": _normalize_feature(global_params.get("SRF_mean")),
            "SRF_std": _normalize_feature(global_params.get("SRF_std")),
        },
    }


def build_domain_record(
    domain: Any,
    *,
    seed: Optional[int] = None,
    joint_sets: Optional[List[Dict[str, Any]]] = None,
    global_params: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    domain_key: str = "domain",
) -> Dict[str, Any]:
    """Build the canonical domain record used by simulation and tests.

    The record contains the domain id, seed, generation features, and a stable
    generation fingerprint so the same data structure can be used both for
    simulation generation and split-validation.
    """
    record = {
        domain_key: domain,
        "seed": seed,
        "joint_sets": list(joint_sets or []),
        "global_params": dict(global_params or {}),
    }
    if extra:
        record.update(extra)
    record["generation_signature"] = generation_signature(record)
    return record


def build_domain_signature_map(
    cases: Iterable[Dict[str, Any]],
    domain_key: str = "domain",
) -> Dict[Any, Dict[str, Any]]:
    """Map each domain to its associated DFN generation signature."""
    domain_map: Dict[Any, Dict[str, Any]] = {}
    for case in cases:
        if domain_key not in case:
            raise KeyError(f"domain key '{domain_key}' missing in case: {case}")
        domain = case[domain_key]
        domain_map[domain] = case.get("generation_signature") or generation_signature(case)
    return domain_map


def domain_signature_hash(signature: Dict[str, Any]) -> str:
    """Convert a generation signature into a stable hash for uniqueness checks."""
    payload = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assert_unique_domain_signatures(cases: Iterable[Dict[str, Any]], domain_key: str = "domain") -> None:
    """Raise ValueError if two different domains share the same generation hash.

    This is the scalable alternative to pairwise comparison: instead of checking
    every domain pair, we hash each domain signature and ensure that the set of
    hashes has the same cardinality as the number of domains.
    """
    sig_map = build_domain_signature_map(cases, domain_key=domain_key)
    hashes = [domain_signature_hash(sig) for sig in sig_map.values()]
    if len(hashes) != len(set(hashes)):
        raise ValueError("Duplicate generation signature detected across domains.")


def validate_domain_split(
    cases: Iterable[Dict[str, Any]],
    domain_key: str = "domain",
    train_frac: float = 0.7,
    random_state: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate split correctness in a single call.

    Returns a summary so large simulation outputs can be checked consistently.
    """
    train_cases, val_cases = split_cases_by_domain(
        list(cases), domain_key=domain_key, train_frac=train_frac, random_state=random_state
    )
    train_domains = {c[domain_key] for c in train_cases}
    val_domains = {c[domain_key] for c in val_cases}
    if not train_domains.isdisjoint(val_domains):
        raise ValueError("Domain leakage detected: the same domain appears in both train and validation.")

    assert_unique_domain_signatures(list(train_cases) + list(val_cases), domain_key=domain_key)

    return {
        "n_train": len(train_cases),
        "n_validation": len(val_cases),
        "train_domains": sorted(train_domains, key=lambda x: str(x)),
        "validation_domains": sorted(val_domains, key=lambda x: str(x)),
        "domain_overlap": sorted(train_domains & val_domains, key=lambda x: str(x)),
    }


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


__all__ = [
    "build_domain_record",
    "split_cases_by_domain",
    "build_manifest",
    "write_manifest",
    "generation_signature",
    "build_domain_signature_map",
    "domain_signature_hash",
    "assert_unique_domain_signatures",
    "validate_domain_split",
]
