const API_BASE = "http://127.0.0.1:8000"

const form = document.querySelector("#search-form")
const queryInput = document.querySelector("#query")
const topicSelect = document.querySelector("#topic")
const statusText = document.querySelector("#status-text")
const resultCount = document.querySelector("#result-count")
const results = document.querySelector("#results")
const cardTemplate = document.querySelector("#result-card-template")

function formatDate(iso) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return iso
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function setStatus(message) {
  statusText.textContent = message
}

function renderResults(items) {
  results.replaceChildren()
  if (!items.length) {
    const empty = document.createElement("article")
    empty.className = "result-card"
    empty.innerHTML = "<h2>No results</h2><p class='preview'>Try broader keywords or a different topic.</p>"
    results.append(empty)
    return
  }

  for (const item of items) {
    const fragment = cardTemplate.content.cloneNode(true)
    fragment.querySelector(".topic-pill").textContent = item.topic
    fragment.querySelector("time").textContent = formatDate(item.published_at)
    fragment.querySelector("h2").textContent = item.title
    fragment.querySelector(".preview").textContent = item.preview
    fragment.querySelector(".source").textContent = item.source

    const link = fragment.querySelector("a")
    link.href = item.url

    results.append(fragment)
  }
}

async function loadTopics() {
  const response = await fetch(`${API_BASE}/api/topics`)
  if (!response.ok) {
    throw new Error("Unable to load topics")
  }
  const payload = await response.json()
  for (const topic of payload.topics) {
    const option = document.createElement("option")
    option.value = topic
    option.textContent = topic
    topicSelect.append(option)
  }
}

async function runSearch() {
  const params = new URLSearchParams()
  const query = queryInput.value.trim()
  const topic = topicSelect.value.trim()
  if (query) params.set("q", query)
  if (topic) params.set("topic", topic)
  params.set("limit", "18")

  setStatus("Searching index...")
  const response = await fetch(`${API_BASE}/api/search?${params.toString()}`)
  if (!response.ok) {
    throw new Error("Search request failed")
  }
  const payload = await response.json()
  renderResults(payload.results)
  resultCount.textContent = `${payload.count} results`
  setStatus(payload.query ? `Query: ${payload.query}` : "Showing newest stories")
}

form.addEventListener("submit", async (event) => {
  event.preventDefault()
  try {
    await runSearch()
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Search failed")
  }
})

;(async () => {
  try {
    await loadTopics()
    await runSearch()
    queryInput.focus()
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Startup failed")
  }
})()
