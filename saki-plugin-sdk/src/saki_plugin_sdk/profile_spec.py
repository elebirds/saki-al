from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _normalize_backend(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"cpu", "cuda", "mps"}:
        return raw
    return ""


@dataclass(frozen=True)
class RuntimeProfileSpec:
    id: str
    priority: int
    when: str
    dependency_groups: list[str] = field(default_factory=list)
    allowed_backends: list[str] = field(default_factory=list)
    entrypoint: str = ""
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "priority": int(self.priority),
            "when": self.when,
            "dependency_groups": list(self.dependency_groups),
            "allowed_backends": list(self.allowed_backends),
            "entrypoint": self.entrypoint,
            "env": dict(self.env),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeProfileSpec":
        profile_id = str(payload.get("id") or "").strip()
        if not profile_id:
            raise ValueError("runtime profile id is required")

        try:
            priority = int(payload.get("priority"))
        except Exception as exc:
            raise ValueError(f"runtime profile priority is required: {profile_id}") from exc

        when = str(payload.get("when") or "").strip()
        if not when:
            raise ValueError(f"runtime profile when is required: {profile_id}")

        dependency_groups_raw = payload.get("dependency_groups")
        if not isinstance(dependency_groups_raw, list) or not dependency_groups_raw:
            raise ValueError(f"runtime profile dependency_groups is required: {profile_id}")
        dependency_groups = []
        seen_groups: set[str] = set()
        for item in dependency_groups_raw:
            value = str(item or "").strip()
            if not value or value in seen_groups:
                continue
            seen_groups.add(value)
            dependency_groups.append(value)
        if not dependency_groups:
            raise ValueError(f"runtime profile dependency_groups is empty: {profile_id}")

        allowed_backends_raw = payload.get("allowed_backends")
        if not isinstance(allowed_backends_raw, list) or not allowed_backends_raw:
            raise ValueError(f"runtime profile allowed_backends is required: {profile_id}")
        allowed_backends = []
        seen_backends: set[str] = set()
        for item in allowed_backends_raw:
            backend = _normalize_backend(item)
            if not backend or backend in seen_backends:
                continue
            seen_backends.add(backend)
            allowed_backends.append(backend)
        if not allowed_backends:
            raise ValueError(f"runtime profile allowed_backends has no valid backend: {profile_id}")

        env_raw = payload.get("env")
        env = {
            str(k): str(v)
            for k, v in (env_raw.items() if isinstance(env_raw, Mapping) else [])
            if str(k).strip()
        }
        return cls(
            id=profile_id,
            priority=priority,
            when=when,
            dependency_groups=dependency_groups,
            allowed_backends=allowed_backends,
            entrypoint=str(payload.get("entrypoint") or "").strip(),
            env=env,
        )


def parse_runtime_profiles(payload: list[dict[str, Any]] | None) -> list[RuntimeProfileSpec]:
    raw_profiles = payload if isinstance(payload, list) else []
    if not raw_profiles:
        return [
            RuntimeProfileSpec(
                id="cpu",
                priority=100,
                when="host.backends.includes('cpu')",
                dependency_groups=["profile-cpu"],
                allowed_backends=["cpu"],
                entrypoint="",
                env={},
            )
        ]

    profiles = [RuntimeProfileSpec.from_dict(item) for item in raw_profiles if isinstance(item, Mapping)]
    if not profiles:
        raise ValueError("runtime_profiles is empty")

    profile_ids = [item.id for item in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("runtime profile id must be unique")

    by_priority: dict[int, list[RuntimeProfileSpec]] = {}
    for profile in profiles:
        by_priority.setdefault(profile.priority, []).append(profile)
    for priority, rows in by_priority.items():
        for left_index in range(len(rows)):
            left = rows[left_index]
            for right in rows[left_index + 1:]:
                same_when = left.when == right.when
                backend_overlap = set(left.allowed_backends) & set(right.allowed_backends)
                if same_when and backend_overlap:
                    raise ValueError(
                        f"runtime profiles overlap on same priority={priority}: "
                        f"{left.id} vs {right.id}, backends={sorted(backend_overlap)}"
                    )
    return sorted(profiles, key=lambda item: (item.priority, item.id))
