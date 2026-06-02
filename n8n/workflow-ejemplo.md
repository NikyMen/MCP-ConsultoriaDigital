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
[3] Code: parsear el JSON del AI Agent { respuesta, pdf }
    │            ├── respuesta → texto para el cliente
    │            └── pdf → clave del presupuesto (o vacío) → archivo + URL
    │
    ├──────────────► [4a] WaSender: enviar TEXTO al telefono
    │
    ▼ (IF pdf != "")
[4b] WaSender: enviar DOCUMENTO (PDF) al telefono
```

La idea central: **el MCP nunca dice precios y nunca arma el presupuesto**. El
AI Agent solo decide *qué PDF* corresponde (vía la tool `presupuesto_pdf`) y
devuelve un **objeto JSON con dos campos**: `respuesta` (lo que ve el cliente) y
`pdf` (la clave del presupuesto a enviar, o vacío). n8n separa ambos: manda el
texto y, si `pdf` no está vacío, adjunta el PDF correspondiente.

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

El prompt instruye al agente a responder **siempre** con un objeto JSON de dos
campos:

```json
{ "respuesta": "texto para el cliente", "pdf": "turneria" }
```

`pdf` es la **clave del presupuesto** (vacío si no corresponde enviar). Hay 4
claves posibles: `rrss_pauta`, `rrss_crm_pauta`, `concilia`, `turneria`.

> Opción recomendada: activá el **Structured Output Parser** del AI Agent con el
> esquema `{ respuesta: string, pdf: string }` para que n8n te entregue el JSON ya
> parseado. Si no lo usás, el Code node de abajo igual lo parsea a mano.

### 3. Code node — separar texto y resolver la ruta del PDF

Después del AI Agent, un nodo **Code** (JavaScript) que lee el JSON y resuelve la
**ruta en disco** del PDF a partir de la clave. (Setup: n8n y el MCP en el mismo
VPS, WaSender envía por binario → leemos el archivo del disco, sin URL pública.)

```js
// Salida del AI Agent: puede venir ya parseada (output parser) o como string JSON
let data = $json.output ?? $json.text ?? $json;
if (typeof data === "string") {
  try { data = JSON.parse(data); } catch (e) { data = { respuesta: data, pdf: "" }; }
}

const texto = (data.respuesta ?? "").trim();
const clave = (data.pdf ?? "").trim();

// Mapeo clave de presupuesto → nombre de archivo (debe coincidir con productos.yaml)
const ARCHIVOS = {
  rrss_pauta:     "presupuesto-rrss-pauta.pdf",
  rrss_crm_pauta: "presupuesto-rrss-crm-pauta.pdf",
  concilia:       "presupuesto-concilia.pdf",
  turneria:       "presupuesto-turneria.pdf",
};
const archivo = ARCHIVOS[clave] ?? "";

// Carpeta donde n8n VE los PDFs.
//  - n8n nativo (sin Docker): la ruta real en el VPS.
//  - n8n en Docker: la ruta DENTRO del contenedor (la que montaste como volumen).
const PDF_DIR = "/data/presupuestos";   // ajustá según tu instalación

return [{
  json: {
    telefono: $json.telefono,
    texto,
    enviar_pdf: archivo !== "",
    pdf_clave: clave,
    pdf_archivo: archivo,
    pdf_path: archivo ? `${PDF_DIR}/${archivo}` : "",
  },
}];
```

### 4. Envío por WaSender (texto + PDF binario)
- **4a — Texto**: nodo WaSender "send message" con `telefono` y `texto`.
- **4b — PDF**: detrás de un nodo **IF** con condición `enviar_pdf == true`:
  1. **Read/Write Files from Disk** → operación **Read**, *File(s) Selector* =
     `{{ $json.pdf_path }}`. Esto carga el PDF como **binario** (propiedad `data`).
  2. **WaSender** en modo **documento/binario**: tomá el binario del paso anterior
     (`data`) y mandalo a `telefono`, con `pdf_archivo` como nombre del archivo.

> **Importante (Docker):** si n8n corre en contenedor, montá la carpeta de PDFs
> como volumen para que el nodo "Read Files from Disk" la vea. En tu
> `docker-compose.yml` / `docker run`, agregá:
> ```
> -v /opt/mcp-consultoria/data/presupuestos:/data/presupuestos:ro
> ```
> y usá `PDF_DIR = "/data/presupuestos"`. Si n8n es nativo (sin Docker), poné la
> ruta real, p. ej. `PDF_DIR = "/opt/mcp-consultoria/data/presupuestos"`.

> **Acceso a archivos en n8n:** si tenés seteada la variable
> `N8N_RESTRICT_FILE_ACCESS_TO`, agregá la carpeta de PDFs a esa lista; si no, el
> nodo "Read Files from Disk" no podrá leerlos.

## Alternativas para hostear los PDFs
1. **Disco local del VPS (tu caso, recomendado)**: PDFs en
   `data/presupuestos/`, n8n los lee con "Read Files from Disk" y WaSender los
   manda como binario. Sin exponer nada público.
2. **Por URL pública**: el MCP también los sirve en `/presupuestos/<archivo>`
   (setear `PRESUPUESTOS_BASE_URL`). Útil si WaSender enviara por URL en vez de
   binario.
3. **Google Drive / Storage**: subir los PDFs y mapear cada clave a su link de
   descarga directa.

## Tips
- El MCP es **sin estado**: no guarda conversaciones ni leads. El contexto lo
  mantiene n8n con `Window Buffer Memory` (sessionKey = `telefono`).
- Antes de hablar de un producto, el agente consulta `info_producto` /
  `faqs_producto` en vez de responder de memoria. **Nunca dice precios.**
- `validar_cuit` cuando el lead pasa un CUIT.
- `presupuesto_pdf` para saber qué PDF mandar. Si devuelve `hay_pdf: false`
  (p. ej. desarrollo a medida), el agente NO manda PDF: ofrece relevamiento.
- La cotización fina y la reunión las coordina el equipo comercial humano.
