const fs = require('fs');

const file = process.env.LIBRECHAT_OPENID_STRATEGY_FILE || '/app/api/strategies/openidStrategy.js';
let source = fs.readFileSync(file, 'utf8');

const functionAnchor = 'async function processOpenIDAuth(tokenset, existingUsersOnly = false) {';
const tenantHelper = `function resolveOpenIdTenantId(claims, userinfo) {
  const claimPath = (process.env.OPENID_TENANT_ID_CLAIM || 'tenantId').trim();
  const claimValue = get(userinfo, claimPath) ?? get(claims, claimPath);
  const tenantId = typeof claimValue === 'string' ? claimValue.trim() : '';

  if (!tenantId) {
    throw new Error(\`OpenID token is missing required tenant claim "\${claimPath}"\`);
  }

  return tenantId;
}

${functionAnchor}`;

if (!source.includes('function resolveOpenIdTenantId(claims, userinfo) {')) {
  if (!source.includes(functionAnchor)) {
    throw new Error('LibreChat OpenID tenant patch anchor not found');
  }
  source = source.replace(functionAnchor, tenantHelper);
}

const userinfoAnchor = `  const userinfo = {
    ...claims,
  };
`;
const userinfoReplacement = `${userinfoAnchor}
  const tenantId = resolveOpenIdTenantId(claims, userinfo);
`;
if (!source.includes(userinfoReplacement)) {
  if (!source.includes(userinfoAnchor)) {
    throw new Error('LibreChat OpenID userinfo patch anchor not found');
  }
  source = source.replace(userinfoAnchor, userinfoReplacement);
}

const createAnchor = `      openidIssuer,
    };`;
const createReplacement = `      openidIssuer,
      tenantId,
    };`;
if (!source.includes(createReplacement)) {
  const position = source.indexOf(createAnchor, source.indexOf('if (!user) {'));
  if (position === -1) {
    throw new Error('LibreChat OpenID user creation patch anchor not found');
  }
  source = source.slice(0, position) + createReplacement + source.slice(position + createAnchor.length);
}

const updateAnchor = `    user.provider = 'openid';
    user.openidId = userinfo.sub;`;
const updateReplacement = `    user.provider = 'openid';
    user.openidId = userinfo.sub;
    user.tenantId = tenantId;`;
if (!source.includes(updateReplacement)) {
  if (!source.includes(updateAnchor)) {
    throw new Error('LibreChat OpenID user update patch anchor not found');
  }
  source = source.replace(updateAnchor, updateReplacement);
}

const persistAnchor = '  user = await updateUser(user._id, user);';
const persistReplacement = `${persistAnchor}

  // Never complete an OpenID login with an unscoped LibreChat user.
  if (user?.tenantId !== tenantId) {
    user = await updateUser(user._id, { tenantId });
  }
  if (user?.tenantId !== tenantId) {
    throw new Error('OpenID tenant claim could not be persisted');
  }`;
if (!source.includes(persistReplacement)) {
  if (!source.includes(persistAnchor)) {
    throw new Error('LibreChat OpenID tenant persistence patch anchor not found');
  }
  source = source.replace(persistAnchor, persistReplacement);
}

fs.writeFileSync(file, source);
