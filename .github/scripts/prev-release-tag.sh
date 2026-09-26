#!/usr/bin/env bash
# .github/scripts/prev-release-tag.sh <plugin> <version>
#
# Resolves the previous release for `release.yml`'s scoped-notes pre-flight.
# Reads candidate tags one per line on stdin (e.g. `git tag -l`) and prints
# the highest `<plugin>--v<semver>` tag that is strictly below `<version>`,
# ordered per SemVer 2.0.0 §11 precedence rules (numeric identifiers compare
# numerically -- `rc.2 < rc.10` -- and rank below alphanumeric ones; a
# release ranks above its own prereleases; with all shared identifiers
# equal, the shorter identifier list is lower).
#
# A candidate tag is skipped, never an error, when it:
#   - starts with `src/` (a history marker on `main`, never itself a
#     previous-release tag -- it has no merge-base with the orphan tags),
#   - does not start with the exact literal `<plugin>--v` prefix (a
#     different plugin's tag),
#   - is not strict SemVer (no leading zeros in any numeric identifier, no
#     build metadata) -- this also folds in the old "Validate version is
#     semver" step's grammar, now applied uniformly to every tag,
#   - is not strictly below `<version>` -- this is what excludes the tag
#     being created itself; a tag equal to `<version>` compares equal, not
#     lower, so no separate self-exclusion check is needed.
#
# With no match (first release, or every tag foreign/invalid) it prints
# nothing and exits 0 -- an empty previous tag is a valid, expected result,
# not a failure.
#
# `<version>` itself must be strict SemVer 2.0.0 too: on failure this prints
# an `::error::` line to stderr and exits 2, distinct from the 0 used for
# "no previous release" so callers can tell "invalid input" from "first
# release" apart.
set -uo pipefail

PLUGIN="${1:-}"
TARGET_VERSION="${2:-}"

if [ -z "$PLUGIN" ] || [ -z "$TARGET_VERSION" ]; then
  echo "::error::usage: prev-release-tag.sh <plugin> <version> (tags on stdin)" >&2
  exit 2
fi

# Strict SemVer 2.0.0 core grammar, no build metadata. Every numeric
# identifier -- the major/minor/patch triplet, and any purely-numeric
# prerelease identifier -- is anchored to reject leading zeros.
SEMVER_RE='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?$'

is_valid_semver() {
  [[ "$1" =~ $SEMVER_RE ]]
}

if ! is_valid_semver "$TARGET_VERSION"; then
  echo "::error::version '$TARGET_VERSION' is not valid SemVer 2.0.0 (expected MAJOR.MINOR.PATCH[-PRERELEASE], no leading zeros, no build metadata)." >&2
  exit 2
fi

# Splits a validated "M.N.P[-PRERELEASE]" string and prints
# "MAJOR\nMINOR\nPATCH\nPRERELEASE" (PRERELEASE is an empty line when
# absent). Caller must have already validated the string.
parse_semver() {
  local v="$1" core pre major rest minor patch
  if [[ "$v" == *-* ]]; then
    core="${v%%-*}"
    pre="${v#*-}"
  else
    core="$v"
    pre=""
  fi
  major="${core%%.*}"
  rest="${core#*.}"
  minor="${rest%%.*}"
  patch="${rest#*.}"
  printf '%s\n%s\n%s\n%s\n' "$major" "$minor" "$patch" "$pre"
}

# Prints -1, 0 or 1 for a<b, a==b, a>b on a single dot-separated identifier,
# per SemVer §11: numeric identifiers compare numerically and always rank
# below alphanumeric ones; otherwise ASCII lexical order applies.
compare_identifier() {
  local a="$1" b="$2" a_num=0 b_num=0
  if [[ "$a" =~ ^[0-9]+$ ]]; then a_num=1; fi
  if [[ "$b" =~ ^[0-9]+$ ]]; then b_num=1; fi

  if [ "$a_num" = 1 ] && [ "$b_num" = 1 ]; then
    local an bn
    an=$((10#$a))
    bn=$((10#$b))
    if [ "$an" -lt "$bn" ]; then echo -1; return 0; fi
    if [ "$an" -gt "$bn" ]; then echo 1; return 0; fi
    echo 0
    return 0
  fi
  if [ "$a_num" = 1 ] && [ "$b_num" = 0 ]; then echo -1; return 0; fi
  if [ "$a_num" = 0 ] && [ "$b_num" = 1 ]; then echo 1; return 0; fi

  if [ "$a" \< "$b" ]; then echo -1; return 0; fi
  if [ "$a" \> "$b" ]; then echo 1; return 0; fi
  echo 0
  return 0
}

# Prints -1, 0 or 1 comparing two prerelease strings (each "" when the
# version has no prerelease) per SemVer §11: no prerelease outranks any
# prerelease; otherwise identifiers are compared left to right, and with all
# shared identifiers equal the longer list wins.
compare_prerelease() {
  local p1="$1" p2="$2"
  if [ -z "$p1" ] && [ -z "$p2" ]; then echo 0; return 0; fi
  if [ -z "$p1" ]; then echo 1; return 0; fi
  if [ -z "$p2" ]; then echo -1; return 0; fi

  local -a a_ids b_ids
  IFS='.' read -ra a_ids <<< "$p1"
  IFS='.' read -ra b_ids <<< "$p2"

  local n=${#a_ids[@]}
  if [ "${#b_ids[@]}" -lt "$n" ]; then n=${#b_ids[@]}; fi

  local i c
  for ((i = 0; i < n; i++)); do
    c=$(compare_identifier "${a_ids[$i]}" "${b_ids[$i]}")
    if [ "$c" != 0 ]; then
      echo "$c"
      return 0
    fi
  done

  if [ "${#a_ids[@]}" -lt "${#b_ids[@]}" ]; then echo -1; return 0; fi
  if [ "${#a_ids[@]}" -gt "${#b_ids[@]}" ]; then echo 1; return 0; fi
  echo 0
  return 0
}

# Prints -1, 0 or 1 comparing two validated SemVer strings by full SemVer
# §11 precedence (major, then minor, then patch, then prerelease).
compare_semver() {
  local v1="$1" v2="$2"
  local a_major a_minor a_patch a_pre
  local b_major b_minor b_patch b_pre
  { read -r a_major; read -r a_minor; read -r a_patch; read -r a_pre; } < <(parse_semver "$v1")
  { read -r b_major; read -r b_minor; read -r b_patch; read -r b_pre; } < <(parse_semver "$v2")

  local c
  c=$(compare_identifier "$a_major" "$b_major")
  if [ "$c" != 0 ]; then echo "$c"; return 0; fi
  c=$(compare_identifier "$a_minor" "$b_minor")
  if [ "$c" != 0 ]; then echo "$c"; return 0; fi
  c=$(compare_identifier "$a_patch" "$b_patch")
  if [ "$c" != 0 ]; then echo "$c"; return 0; fi
  compare_prerelease "$a_pre" "$b_pre"
}

PLUGIN_PREFIX="${PLUGIN}--v"
BEST_VERSION=""
BEST_TAG=""

while IFS= read -r line || [ -n "$line" ]; do
  # Strip a trailing CR: stdin may arrive CRLF-terminated (e.g. a Windows
  # text-mode pipe from a calling process), and a stray CR left on the line
  # would make every candidate fail is_valid_semver below.
  line="${line%$'\r'}"
  if [ -z "$line" ]; then
    continue
  fi
  case "$line" in
    src/*)
      continue
      ;;
  esac
  case "$line" in
    "$PLUGIN_PREFIX"*)
      ;;
    *)
      continue
      ;;
  esac

  candidate_version="${line#"$PLUGIN_PREFIX"}"
  if ! is_valid_semver "$candidate_version"; then
    continue
  fi

  cmp=$(compare_semver "$candidate_version" "$TARGET_VERSION")
  if [ "$cmp" != -1 ]; then
    continue
  fi

  if [ -z "$BEST_VERSION" ]; then
    BEST_VERSION="$candidate_version"
    BEST_TAG="$line"
    continue
  fi

  cmp2=$(compare_semver "$candidate_version" "$BEST_VERSION")
  if [ "$cmp2" = 1 ]; then
    BEST_VERSION="$candidate_version"
    BEST_TAG="$line"
  fi
done

if [ -n "$BEST_TAG" ]; then
  printf '%s\n' "$BEST_TAG"
fi

exit 0
