// Validates the post-login `?redirect=` target. It arrives in the URL, so it is
// attacker-controlled: only an in-app path is allowed, anything else lands on '/'.
// Accepted: a string starting with exactly one '/' whose next character is not
// '/' or '\' (browsers treat '\' like '/', so '/\evil.com' is protocol-relative),
// containing no control characters or whitespace (browsers strip tab/CR/LF out of
// URLs, so '/\t/evil.com' would collapse to '//evil.com') and no backslash at all.
export function safeRedirect(target) {
  if (typeof target !== 'string') return '/'
  if (target.length < 1 || target[0] !== '/') return '/'
  if (target[1] === '/') return '/'
  // eslint-disable-next-line no-control-regex
  if (/[\\\s\u0000-\u001f\u007f]/.test(target)) return '/'
  return target
}
