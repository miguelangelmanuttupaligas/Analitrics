const express = require('express');
const cookies = require('cookie');
const jwt = require('jsonwebtoken');
const { logger } = require('@librechat/data-schemas');
const { getUserById, findUser } = require('~/models');

const router = express.Router();

const userProjection = '-password -__v -totpSecret -backupCodes';

const normalizeUser = (user) => {
  if (!user) {
    return null;
  }
  user.id = user._id?.toString?.() || user.id?.toString?.();
  return user.id ? user : null;
};

const getBearerToken = (req) => {
  const header = req.headers.authorization || '';
  const match = header.match(/^Bearer\s+(.+)$/i);
  return match ? match[1] : null;
};

const getUserFromJwt = async (token, secret) => {
  if (!token || !secret) {
    return null;
  }
  try {
    const payload = jwt.verify(token, secret);
    if (!payload?.id) {
      return null;
    }
    return normalizeUser(await getUserById(payload.id, userProjection));
  } catch {
    return null;
  }
};

const getUserFromOpenIdSession = async (req) => {
  const idToken = req.session?.openidTokens?.idToken;
  if (!idToken) {
    return null;
  }
  const claims = jwt.decode(idToken);
  if (!claims || typeof claims !== 'object') {
    return null;
  }

  if (claims.sub) {
    const byOpenId = await findUser({ openidId: claims.sub }, userProjection);
    if (byOpenId) {
      return normalizeUser(byOpenId);
    }
  }
  if (claims.email) {
    const byEmail = await findUser({ email: claims.email }, userProjection);
    if (byEmail) {
      return normalizeUser(byEmail);
    }
  }
  return null;
};

const requireAnalitricsAuth = async (req, res, next) => {
  try {
    const parsedCookies = req.headers.cookie ? cookies.parse(req.headers.cookie) : {};
    const user =
      (await getUserFromJwt(getBearerToken(req), process.env.JWT_SECRET)) ||
      (await getUserFromJwt(parsedCookies.openid_user_id, process.env.JWT_REFRESH_SECRET)) ||
      (await getUserFromOpenIdSession(req));

    if (!user) {
      return res.status(401).json({ ok: false, error: 'Unauthorized' });
    }
    req.user = user;
    next();
  } catch (error) {
    logger.warn('[AnalitricsContext] Auth resolution failed: ' + error.message);
    return res.status(401).json({ ok: false, error: 'Unauthorized' });
  }
};

router.use(requireAnalitricsAuth);

router.get('/context', async (req, res) => {
  const conversationId = String(req.query.conversationId || '');
  if (!conversationId) {
    return res.status(400).json({ ok: false, error: 'conversationId is required' });
  }

  const tenantId = req.user?.tenantId || req.headers['x-tenant-id'] || 'analitrics';
  const userId = String(req.user.id);
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';
  const params = new URLSearchParams({
    tenantId: String(tenantId),
    userId,
    conversationId,
  });

  try {
    const response = await fetch(agentOrigin + '/agent/context?' + params.toString());
    const payload = await response.json().catch(() => ({}));
    return res.status(response.status).json(payload);
  } catch (error) {
    logger.warn('[AnalitricsContext] Agent context unavailable: ' + error.message);
    return res.status(502).json({ ok: false, error: 'Analitrics context unavailable' });
  }
});

const analitricsIdentity = (req) => ({
  tenantId: String(req.user?.tenantId || req.headers['x-tenant-id'] || 'analitrics'),
  userId: String(req.user.id),
});

router.get('/dashboards', async (req, res) => {
  const { tenantId, userId } = analitricsIdentity(req);
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';
  const params = new URLSearchParams({ tenantId, userId });

  try {
    const response = await fetch(agentOrigin + '/agent/dashboards?' + params.toString());
    const payload = await response.json().catch(() => ({}));
    return res.status(response.status).json(payload);
  } catch (error) {
    logger.warn('[AnalitricsDashboards] Agent unavailable: ' + error.message);
    return res.status(502).json({ ok: false, error: 'Analitrics dashboards unavailable' });
  }
});

router.get('/dashboards/:dashboardId', async (req, res) => {
  const dashboardId = String(req.params.dashboardId || '');
  if (!dashboardId) {
    return res.status(400).json({ ok: false, error: 'dashboardId is required' });
  }
  const { tenantId, userId } = analitricsIdentity(req);
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';
  const params = new URLSearchParams({ tenantId, userId });

  try {
    const response = await fetch(
      agentOrigin + '/agent/dashboards/' + encodeURIComponent(dashboardId) + '?' + params.toString(),
    );
    const payload = await response.json().catch(() => ({}));
    return res.status(response.status).json(payload);
  } catch (error) {
    logger.warn('[AnalitricsDashboard] Agent unavailable: ' + error.message);
    return res.status(502).json({ ok: false, error: 'Analitrics dashboard unavailable' });
  }
});

router.post('/dashboards', async (req, res) => {
  const conversationId = String(req.body?.conversationId || '');
  const title = req.body?.title ? String(req.body.title) : undefined;
  if (!conversationId) {
    return res.status(400).json({ ok: false, error: 'conversationId is required' });
  }
  const { tenantId, userId } = analitricsIdentity(req);
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';

  try {
    const response = await fetch(agentOrigin + '/agent/dashboards', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tenantId, userId, conversationId, title }),
    });
    const payload = await response.json().catch(() => ({}));
    return res.status(response.status).json(payload);
  } catch (error) {
    logger.warn('[AnalitricsDashboardCreate] Agent unavailable: ' + error.message);
    return res.status(502).json({ ok: false, error: 'Analitrics dashboard creation unavailable' });
  }
});

router.post('/dashboards/:dashboardId/views/:viewId/run', async (req, res) => {
  const dashboardId = String(req.params.dashboardId || '');
  const viewId = String(req.params.viewId || '');
  if (!dashboardId || !viewId) {
    return res.status(400).json({ ok: false, error: 'dashboardId and viewId are required' });
  }
  const { tenantId, userId } = analitricsIdentity(req);
  const limit = Number(req.body?.limit || 200);
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';

  try {
    const response = await fetch(
      agentOrigin +
        '/agent/dashboards/' +
        encodeURIComponent(dashboardId) +
        '/views/' +
        encodeURIComponent(viewId) +
        '/run',
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tenantId, userId, limit }),
      },
    );
    const payload = await response.json().catch(() => ({}));
    return res.status(response.status).json(payload);
  } catch (error) {
    logger.warn('[AnalitricsDashboardRun] Agent unavailable: ' + error.message);
    return res.status(502).json({ ok: false, error: 'Analitrics dashboard run unavailable' });
  }
});

router.post('/dashboards/:dashboardId/instructions', async (req, res) => {
  const dashboardId = String(req.params.dashboardId || '');
  const instruction = String(req.body?.instruction || '');
  if (!dashboardId) {
    return res.status(400).json({ ok: false, error: 'dashboardId is required' });
  }
  if (!instruction.trim()) {
    return res.status(400).json({ ok: false, error: 'instruction is required' });
  }
  const { tenantId, userId } = analitricsIdentity(req);
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';

  try {
    const response = await fetch(
      agentOrigin + '/agent/dashboards/' + encodeURIComponent(dashboardId) + '/instructions',
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tenantId, userId, instruction }),
      },
    );
    const payload = await response.json().catch(() => ({}));
    return res.status(response.status).json(payload);
  } catch (error) {
    logger.warn('[AnalitricsDashboardInstruction] Agent unavailable: ' + error.message);
    return res.status(502).json({ ok: false, error: 'Analitrics dashboard instruction unavailable' });
  }
});

router.post('/catalog/feedback', async (req, res) => {
  const conversationId = String(req.body?.conversationId || '');
  const step = Number(req.body?.step || 0);
  const label = String(req.body?.label || '');
  const content = String(req.body?.content || '');
  const sourceFileId = req.body?.sourceFileId ? String(req.body.sourceFileId) : null;
  const sourceFilename = req.body?.sourceFilename ? String(req.body.sourceFilename) : null;
  if (!conversationId) {
    return res.status(400).json({ ok: false, error: 'conversationId is required' });
  }
  if (!Number.isInteger(step) || step < 1 || step > 6) {
    return res.status(400).json({ ok: false, error: 'step must be between 1 and 6' });
  }
  if (!content.trim()) {
    return res.status(400).json({ ok: false, error: 'content is required' });
  }

  const tenantId = req.user?.tenantId || req.headers['x-tenant-id'] || 'analitrics';
  const userId = String(req.user.id);
  const agentOrigin = process.env.ANALITRICS_AGENT_ORIGIN || 'http://analytics-agent:8090';

  try {
    const response = await fetch(agentOrigin + '/agent/catalog/feedback', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        tenantId: String(tenantId),
        userId,
        conversationId,
        sourceFileId,
        sourceFilename,
        step,
        label,
        content,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    return res.status(response.status).json(payload);
  } catch (error) {
    logger.warn('[AnalitricsCatalogFeedback] Agent unavailable: ' + error.message);
    return res.status(502).json({ ok: false, error: 'Analitrics catalog feedback unavailable' });
  }
});

module.exports = router;
