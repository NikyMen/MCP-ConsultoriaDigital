# Workflow de ejemplo en n8n

## Arquitectura

```
WaSender (webhook IN)
    │
    ▼
n8n: normalizar payload (telefono, texto, nombre)
    │
    ▼
n8n: AI Agent (modelo GPT-4o/4o-mini)
    ├── System prompt: el que devuelve `prompt_sistema` del MCP
    └── Tools: MCP Client node → http(s)://VPS/mcp/  (Authorization: Bearer ...)
    │
    ▼
n8n: WaSender (enviar respuesta)
```

## Pasos para configurarlo

1. **MCP Client node**
   - Endpoint: `https://tu-dominio.com/mcp/`
   - Auth: `Header Auth` → header `Authorization` con valor `Bearer <MCP_AUTH_TOKEN>`
   - Transport: streamable HTTP (el default de FastMCP).
   - Tools: importar todas. El agent decide cuáles llamar.

2. **AI Agent node (OpenAI Functions / Tools agent)**
   - Modelo: gpt-4o o gpt-4o-mini.
   - System message: llamar primero el tool `prompt_sistema` y pegar la respuesta
     ahí, o cachearlo en una variable de entorno de n8n.
   - Memory: usar `Window Buffer Memory` con sessionKey = `telefono` del lead
     para mantener contexto por conversación.
   - User message: el texto recibido por WaSender.

3. **WaSender (IN)**
   - Configurar un webhook que dispare el workflow ante cada mensaje entrante.
   - Mapear: `telefono` (wa_id) y `texto` al nodo de normalización.

4. **WaSender (OUT)**
   - Tras la respuesta del agente, enviar el texto al `telefono`.
   - Si el agente devuelve un link de presupuesto, mandarlo en un segundo
     mensaje (o adjuntar el PDF si tu plan de WaSender lo permite).

## Tips

- El primer mensaje del agente para cada nuevo lead debería llamar
  `buscar_lead(telefono)` para saber si ya existe estado previo.
- Después de cada turno relevante, `registrar_lead` con los datos nuevos.
- `generar_presupuesto` solo cuando el lead ya tiene CUIT válido + empresa.
- Antes de pasar el lead a `ALTA`, el agente ya envió el PDF y propuso
  reunión (el tool `generar_presupuesto` setea esta clasificación automáticamente).
