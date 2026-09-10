import { NextRequest } from "next/server";
import { accessToken } from "@/lib/supabase/server";

/**
 * Transparent proxy to the FastAPI backend.
 *
 * Keeps BACKEND_URL server-side, avoids CORS in the browser, and lets file
 * uploads stream through unchanged. Long-running work (a 318MB workbook
 * import) is started here but tracked via /api/jobs, so no request is held
 * open for the duration.
 *
 * It also attaches the caller identity. The session lives in cookies, and the
 * backend wants a bearer token, so the token is read here and forwarded. Doing
 * it in the proxy rather than in each fetch is what makes a plain download
 * link work: a browser navigation sends cookies but never an Authorization
 * header.
 */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

async function proxy(request: NextRequest, path: string[]) {
  const target = `${BACKEND_URL}/${path.join("/")}${request.nextUrl.search}`;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  const token = await accessToken();
  if (token) headers.set("authorization", `Bearer ${token}`);

  const method = request.method;
  const hasBody = method !== "GET" && method !== "HEAD";

  try {
    const response = await fetch(target, {
      method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      // @ts-expect-error - duplex is required by Node's fetch for streamed bodies
      duplex: "half",
    });

    return new Response(response.body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json",
        ...(response.headers.get("content-disposition")
          ? { "content-disposition": response.headers.get("content-disposition")! }
          : {}),
      },
    });
  } catch {
    return Response.json(
      {
        detail:
          `Cannot reach the extraction backend at ${BACKEND_URL}. ` +
          `Start it with:  cd control-panel/backend && python main.py`,
      },
      { status: 503 },
    );
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}
