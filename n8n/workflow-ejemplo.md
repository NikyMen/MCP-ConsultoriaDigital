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
    ├── System prompt: configurado en el propio nodo del AI Agent
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
   - System message: pegar el prompt del agente comercial directamente en el
     nodo (el MCP ya no lo expone como tool).
   - Memory: usar `Window Buffer Memory` con sessionKey = `telefono` del lead
     para mantener contexto por conversación.
   - User message: el texto recibido por WaSender.

3. **WaSender (IN)**
   - Configurar un webhook que dispare el workflow ante cada mensaje entrante.
   - Mapear: `telefono` (wa_id) y `texto` al nodo de normalización.

4. **WaSender (OUT)**
   - Tras la respuesta del agente, enviar el texto al `telefono`.

## Tips

- El MCP es **sin estado**: no guarda conversaciones ni leads. El contexto por
  conversación lo mantiene n8n con `Window Buffer Memory` (sessionKey =
  `telefono`).
- Antes de responder algo de un producto, el agente debería consultar
  `info_producto` / `faqs_producto` en vez de responder de memoria.
- `validar_cuit` cuando el lead pasa un CUIT, para confirmar que es válido.
- La cotización y la reunión las coordina el equipo comercial humano (el MCP ya
  no genera PDFs ni agenda). Si querés persistir leads o sincronizar con un CRM,
  hacelo con nodos de n8n.
