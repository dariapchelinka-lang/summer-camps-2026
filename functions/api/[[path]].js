// functions/api/[[path]].js - прокси для API запросов
export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  
  // Если запрос к API - проксируем на ваш бэкенд
  const apiPaths = ['/submit', '/health', '/admin'];
  if (apiPaths.some(path => url.pathname === path || url.pathname.startsWith('/admin'))) {
    
    // Замените на ваш URL после деплоя на Render/Railway
    const backendUrl = env.BACKEND_URL || 'https://summer-camps-2026.onrender.com';
    const backendRequest = new Request(backendUrl + url.pathname + url.search, {
      method: request.method,
      headers: request.headers,
      body: request.body
    });
    
    // Добавляем CORS для безопасности
    const response = await fetch(backendRequest);
    const newHeaders = new Headers(response.headers);
    newHeaders.set('Access-Control-Allow-Origin', '*');
    
    return new Response(response.body, {
      status: response.status,
      headers: newHeaders
    });
  }
  
  // Остальные запросы (статика) обрабатывает Cloudflare Pages
  return fetch(request);
}
