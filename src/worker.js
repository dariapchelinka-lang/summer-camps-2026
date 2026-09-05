// src/worker.js
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    
    // Маршруты API
    if (url.pathname === '/api/submit') {
      return handleSubmit(request, env);
    }
    if (url.pathname === '/api/health') {
      return new Response(JSON.stringify({ status: 'ok', service: 'cloudflare-worker' }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    // Статика и HTML
    return fetch(request);
  }
};

async function handleSubmit(request, env) {
  try {
    const formData = await request.formData();
    const values = Object.fromEntries(formData);
    
    // Здесь нужно вызвать Python через API
    // Используем внешний сервер или Python на Workers через Pyodide
    
    return new Response(JSON.stringify({ success: true }), {
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
