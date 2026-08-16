ARG LIBRECHAT_IMAGE=registry.librechat.ai/danny-avila/librechat@sha256:c5db3331b845e1f289f8d04c0c77936c4bbe372f76730a804abc1c37e44d23a9
FROM ${LIBRECHAT_IMAGE}

USER root

RUN node - <<'NODE'
const fs = require('fs');
const file = '/app/packages/api/dist/index.cjs';
const original = fs.readFileSync(file, 'utf8');
const before = `function isAdminPanelRedirect(redirectUri, adminPanelUrl, domainClient) {
\ttry {
\t\tconst redirectOrigin = new URL(redirectUri).origin;
\t\tconst adminOrigin = new URL(adminPanelUrl).origin;
\t\tconst clientOrigin = new URL(domainClient).origin;
\t\t/** Redirect is for admin panel if it matches admin origin but not main client origin */
\t\treturn redirectOrigin === adminOrigin && redirectOrigin !== clientOrigin;
\t} catch {
\t\t/** If URL parsing fails, fall back to simple string comparison */
\t\treturn redirectUri.startsWith(adminPanelUrl) && !redirectUri.startsWith(domainClient);
\t}
}`;
const after = `function isAdminPanelRedirect(redirectUri, adminPanelUrl, domainClient) {
\ttry {
\t\tconst redirectUrl = new URL(redirectUri);
\t\tconst adminUrl = new URL(adminPanelUrl);
\t\tconst clientUrl = new URL(domainClient);
\t\tconst normalizedAdminPath = adminUrl.pathname.endsWith('/') ? adminUrl.pathname.slice(0, -1) : adminUrl.pathname;
\t\tconst adminPathMatches = normalizedAdminPath === '' || redirectUrl.pathname === normalizedAdminPath || redirectUrl.pathname.startsWith(normalizedAdminPath + '/');
\t\tif (redirectUrl.origin === adminUrl.origin && adminPathMatches) {
\t\t\treturn true;
\t\t}
\t\treturn redirectUrl.origin === adminUrl.origin && redirectUrl.origin !== clientUrl.origin;
\t} catch {
\t\treturn redirectUri.startsWith(adminPanelUrl);
\t}
}`;
if (!original.includes(before)) {
  throw new Error('LibreChat admin redirect patch target not found');
}
fs.writeFileSync(file, original.replace(before, after));
NODE
