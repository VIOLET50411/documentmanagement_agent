import { apiGet } from "./http"

export const searchApi = {
  search(query: string, options: Record<string, unknown> = {}) {
    return apiGet("/search/", {
      params: { q: query, ...options },
    })
  },
}
