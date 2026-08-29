"""Shared metadata-only fixtures for the coordinator encoding boundary."""


def _split_every(value: str, interval: int, separator: str) -> str:
    return separator.join(
        value[offset : offset + interval]
        for offset in range(0, len(value), interval)
    )


_BASE64_BODY = "QUFB" * 12
_BASE64URL_BODY = "QUFB-___" * 6
_SEPARATORS = (("space", " "), ("tab", "\t"), ("crlf", "\r\n"))

STRUCTURAL_ENCODING_CASES = tuple(
    (
        f"base64-{separator_name}-interval-{interval}",
        _split_every(_BASE64_BODY, interval, separator),
    )
    for index, interval in enumerate((1, 2, 3, 4, 5, 6, 7, 8, 12))
    for separator_name, separator in (_SEPARATORS[index % len(_SEPARATORS)],)
) + (
    ("base64-single-token", _BASE64_BODY),
    ("base64url-space-interval-5", _split_every(_BASE64URL_BODY, 5, " ")),
    ("base64url-crlf-interval-8", _split_every(_BASE64URL_BODY, 8, "\r\n")),
    (
        "base64-final-padding",
        _split_every(("QUFB" * 8) + "QQ", 5, "\t") + "==",
    ),
    ("base64-low-entropy", "A" * 64),
) + tuple(
    (
        f"independently-padded-{separator_name}-{fragment_count}",
        separator.join(["QQ=="] * fragment_count),
    )
    for fragment_count in range(8, 17)
    for separator_name, separator in (
        _SEPARATORS[(fragment_count - 8) % len(_SEPARATORS)],
    )
)

HARMLESS_PROSE_CONTROL = "The compact report is ready; no embedded payload is present."
TYPED_SAFE_ID_CONTROL = "A" * 64
TYPED_CHECKSUM_CONTROL = "abcdef0123456789" * 4
TYPED_CHECKSUM_TEXT_CONTROL = f"sha512={TYPED_CHECKSUM_CONTROL}"
