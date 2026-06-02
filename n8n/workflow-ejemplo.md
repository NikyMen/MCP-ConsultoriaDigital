# Workflow de ejemplo en n8n

## Arquitectura

```
WaSender (webhook IN)
    │
    ▼
[1] Normalizar payload (telefono, texto, nombre)
    │
    ▼
[2] AI Agent (GPT-4o / 4o-mini)
    ├── System prompt: prompts/system_prompt.md (pegado en el nodo)
    ├── Memory: Window Buffer Memory (sessionKey = telefono)
    └── Tools: MCP Client → https://VPS/mcp/  (Authorization: Bearer ...)
    │
    ▼
[3] Code: parsear marcador [[ENVIAR_PDF: archivo]]
    │            ├── texto limpio (sin el marcador)
    │            └── archivo del PDF (o vacío)
    │
    ├──────────────► [4a] WaSender: enviar TEXTO al telefono
    │
    ▼ (IF archivo != "")
[4b] WaSender: enviar DOCUMENTO (PDF) al telefono
```

La idea central: **el MCP nunca dice precios y nunca arma el presupuesto**. El
AI Agent solo decide *qué PDF* corresponde (vía la tool `presupuesto_pdf`) y lo
**señala** con un marcador al final de su respuesta. n8n detecta ese marcador,
manda el PDF y borra el marcador del texto antes de enviárselo al cliente.

## Pasos para configurarlo

### 1. MCP Client node
- Endpoint: `https://tu-dominio.com/mcp/`
- Auth: `Header Auth` → header `Authorization` = `Bearer <MCP_AUTH_TOKEN>`
- Transport: streamable HTTP (default de FastMCP).
- Tools: importar todas. El agent decide cuáles llamar.

### 2. AI Agent node (OpenAI Functions / Tools agent)
- Modelo: gpt-4o o gpt-4o-mini.
- System message: pegar **`prompts/system_prompt.md`** tal cual.
- Memory: `Window Buffer Memory` con sessionKey = `telefono` (mantiene contexto
  por conversación; el MCP es sin estado).
- User message: el texto recibido por WaSender.

El prompt instruye al agente a, cuando corresponde enviar presupuesto, terminar
su respuesta con una línea:

```
[[ENVIAR_PDF: presupuesto-turneria.pdf]]
```

donde el nombre sale de la tool `presupuesto_pdf`.

### 3. Code node — separar texto y PDF

Después del AI Agent, un nodo **Code** (JavaScript) que parsea el marcador:

```js
const salida = $json.output ?? $json.text ?? "";
const re = /\[\[ENVIAR_PDF:\s*([^\]]+?)\s*\]\]/i;
const m = salida.match(re);

const archivo = m ? m[1].trim() : "";
const textoLimpio = salida.replace(re, "").trim();

// Base pública de los PDFs (igual que PRESUPUESTOS_BASE_URL en el .env del MCP)
const BASE = "https://tu-dominio.com/presupuestos";

return [{
  json: {
    telefono: $json.telefono,
    texto: textoLimpio,
    enviar_pdf: archivo !== "",
    pdf_archivo: archivo,
    pdf_url: archivo ? `${BASE}/${archivo}` : "",
  },
}];
```

### 4. Envío por WaSender
- **4a — Texto**: nodo WaSender "send message" con `telefono` y `texto`.
- **4b — Documento**: un nodo **IF** con condición `enviar_pdf == true`; por la
  rama true, un WaSender "send document/media" usando `pdf_url` (y `pdf_archivo`
  como nombre de archivo).

> WaSender necesita una **URL pública** del PDF. Por eso el MCP sirve los PDFs en
> `/presupuestos/<archivo>` (ruta pública, sin auth). Asegurate de que el dominio
> apunte al VPS y que `PRESUPUESTOS_BASE_URL` coincida con `BASE` del Code node.

## Alternativas para hostear los PDFs
1. **VPS (recomendado, ya incluido)**: dejá los PDFs en `data/presupuestos/`; el
   server los sirve en `/presupuestos/`. Cero infra extra.
2. **Google Drive / Storage**: subí los PDFs y mapeá el nombre de archivo a su
   link de descarga directa en el Code node. Útil si no querés exponerlos en el VPS.
3. **Binario en n8n**: un nodo *HTTP Request* baja el PDF desde la URL y lo pasa
   como binario al nodo de WaSender (si tu versión de WaSender pide binario en vez
   de URL).

## Tips
- El MCP es **sin estado**: no guarda conversaciones ni leads. El contexto lo
  mantiene n8n con `Window Buffer Memory` (sessionKey = `telefono`).
- Antes de hablar de un producto, el agente consulta `info_producto` /
  `faqs_producto` en vez de responder de memoria. **Nunca dice precios.**
- `validar_cuit` cuando el lead pasa un CUIT.
- `presupuesto_pdf` para saber qué PDF mandar. Si devuelve `hay_pdf: false`
  (p. ej. desarrollo a medida), el agente NO manda PDF: ofrece relevamiento.
- La cotización fina y la reunión las coordina el equipo comercial humano.
