#!/usr/bin/env bash
# .github/scripts/marketplace-payload.sh
#
# Builds the marketplace dispatch payload with a single `jq`, replacing the
# old heredoc in release.yml. A heredoc can't JSON-escape a multi-line
# changelog (quotes, backslashes, backticks, `$(...)`/`${...}` shell
# metacharacters, CRLF, unicode) -- jq does, byte-for-byte.
#
# All inputs are read from environment variables (NAME, DESC, REPO,
# VERSION, TAG, optional CHANGELOG), never from a positional CLI argument --
# nothing here is a plain flag a caller could bypass by forgetting to quote.
#
# Inputs are handed to jq via `--arg` (i.e. through argv, one bash variable
# expansion per value), NOT through jq's `$ENV` builtin. This is a
# deliberate deviation from reading them via `$ENV`: `jq`'s Windows build
# reads the process environment through the ANSI (codepage) environment
# block rather than the wide/UTF-8 one, so `$ENV.CHANGELOG` silently
# corrupts any non-ASCII byte on windows-latest runners (verified empirically
# while making tests/test_release_scripts.py::test_payload_hostile_changelog_roundtrip
# green: caf\xc3\xa9 came back as caf\xef\xbf\xbd, and each Japanese
# character came back as a literal "?" -- textbook WideCharToMultiByte
# best-fit replacement). `--arg` does not have this problem: bash expands
# "$CHANGELOG" to a single argv token before jq ever touches the process
# environment, so the value that reaches jq is exactly the byte sequence
# git-bash's own (UTF-8-correct) variable substitution produced.
# `MSYS_NO_PATHCONV=1` is exported here too, defensively, in case a future
# caller invokes this script without already setting it: MSYS auto-converts
# an argv value that looks like a whole POSIX path (e.g. a changelog whose
# entire text is "/usr/local/bin") into a Windows path before handing it to
# the (non-MSYS) jq.exe; a value that merely contains such a path inside a
# longer string is unaffected either way, but a value that IS exactly one
# is not, hence the belt-and-suspenders export.
#
# Optional: CHANGELOG -- when unset or empty, the `changelog` key is omitted
# entirely rather than sent as `""` or `null` (the marketplace consumer
# treats the key as optional).
set -uo pipefail
export MSYS_NO_PATHCONV=1

NAME="${NAME:-}"
DESC="${DESC:-}"
REPO="${REPO:-}"
VERSION="${VERSION:-}"
TAG="${TAG:-}"
CHANGELOG="${CHANGELOG:-}"

jq -n \
  --arg name "$NAME" \
  --arg desc "$DESC" \
  --arg repo "$REPO" \
  --arg version "$VERSION" \
  --arg tag "$TAG" \
  --arg changelog "$CHANGELOG" \
  '
  {
    event_type: "plugin-release",
    client_payload: (
      {
        name: $name,
        description: $desc,
        repo: $repo,
        category: "skill",
        version: $version,
        ref: $tag,
        icon: ("https://raw.githubusercontent.com/" + $repo + "/" + $tag + "/assets/icon.png"),
        description_url: ("https://raw.githubusercontent.com/" + $repo + "/" + $tag + "/description.md"),
        tags: ["3d", "creative"]
      }
      + (
          if ($changelog != "")
          then { changelog: $changelog }
          else {}
          end
        )
    )
  }
'
