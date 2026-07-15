export type JsonObject = Record<string, any>

export class ApiError extends Error {
  status: number
  payload: JsonObject

  constructor(message: string, status: number, payload: JsonObject = {}) {
    super(message)
    this.status = status
    this.payload = payload
  }
}

export async function api<T extends JsonObject>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json; charset=utf-8')
  }
  const response = await fetch(url, { ...options, headers })
  const payload = (await response.json()) as JsonObject
  if (!response.ok || payload.ok === false) {
    throw new ApiError(payload.error || `HTTP ${response.status}`, response.status, payload)
  }
  return payload as T
}

export function queryString(values: Record<string, string>): string {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  const text = params.toString()
  return text ? `?${text}` : ''
}
