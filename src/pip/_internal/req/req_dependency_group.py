import optparse
import re
from collections import defaultdict
from typing import List, Optional, TYPE_CHECKING

from pip._vendor import tomli
from pip._internal.exceptions import InstallationError
from pip._internal.network.session import PipSession
from pip._vendor.packaging.requirements import Requirement

if TYPE_CHECKING:
    from pip._internal.index.package_finder import PackageFinder


_NAME_NORMALIZATION_PATTERN = re.compile(r"[-_.]+")


def parse_dependency_group(
    group: str,
    session: PipSession,
    finder: Optional["PackageFinder"] = None,
    options: Optional[optparse.Values] = None,
) -> List[str]:
    try:
        with open("pyproject.toml", "rb") as fp:
            pyproject = tomli.load(fp)
    except FileNotFoundError:
        raise InstallationError("pyproject.toml not found. Cannot resolve '--dependency-group' options.")
    except tomli.TOMLError as e:
        raise InstallationError(f"Error parsing pyproject.toml: {e}") from e
    except OSError as e:
        raise InstallationError(f"Error reading pyproject.toml: {e}") from e

    if "dependency-groups" not in pyproject:
        raise InstallationError("[dependency-groups] table was missing. Cannot resolve '--dependency-group' options.")
    raw_dependency_groups = pyproject["dependency-groups"]
    if not isinstance(raw_dependency_groups, dict):
        raise InstallationError("[dependency-groups] table was malformed. Cannot resolve '--dependency-group' options.")
    dependency_groups = _normalize_group_names(raw_dependency_groups)

    try:
        return _resolve_dependency_group(dependency_groups, group)
    except (ValueError, LookupError) as e:
        raise InstallationError("[dependency-groups] resolution failed: {e}") from e


def _normalize_name(name: str) -> str:
    return _NAME_NORMALIZATION_PATTERN.sub("-", name).lower()


def _normalize_group_names(dependency_groups: dict) -> dict:
    original_names = defaultdict(list)
    normalized_groups = {}

    for group_name, value in dependency_groups.items():
        normed_group_name = _normalize_name(group_name)
        original_names[normed_group_name].append(group_name)
        normalized_groups[normed_group_name] = value

    errors = []
    for normed_name, names in original_names.items():
        if len(names) > 1:
            errors.append(f"{normed_name} ({', '.join(names)})")
    if errors:
        raise ValueError(f"Duplicate dependency group names: {', '.join(errors)}")

    return normalized_groups


def _resolve_dependency_group(
    dependency_groups: dict, group: str, past_groups: tuple[str] = ()
) -> list[str]:
    if group in past_groups:
        raise ValueError(f"Cyclic dependency group include: {group} -> {past_groups}")

    if group not in dependency_groups:
        raise LookupError(f"Dependency group '{group}' not found")

    raw_group = dependency_groups[group]
    if not isinstance(raw_group, list):
        raise ValueError(f"Dependency group '{group}' is not a list")

    realized_group = []
    for item in raw_group:
        if isinstance(item, str):
            # packaging.requirements.Requirement parsing ensures that this is a valid
            # PEP 508 Dependency Specifier
            # raises InvalidRequirement on failure
            Requirement(item)
            realized_group.append(item)
        elif isinstance(item, dict):
            if tuple(item.keys()) != ("include",):
                raise ValueError(f"Invalid dependency group item: {item}")

            include_group = _normalize_name(next(iter(item.values())))
            realized_group.extend(
                _resolve_dependency_group(
                    dependency_groups, include_group, past_groups + (group,)
                )
            )
        else:
            raise ValueError(f"Invalid dependency group item: {item}")

    return realized_group
