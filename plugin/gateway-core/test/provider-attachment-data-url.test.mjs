import assert from "node:assert/strict"
import test from "node:test"

import {
  isCanonicalStructurallyValidPngDataUrl,
  isStructurallyValidPngContainer,
  MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS,
  MAX_OPAQUE_ATTACHMENT_DECODED_BYTES,
  OPAQUE_PROVIDER_ATTACHMENT_MIME_TYPES,
  parseCanonicalProviderAttachmentDataUrl,
  MAX_OPAQUE_PNG_CHUNKS,
  MAX_OPAQUE_PNG_DATA_URL_CHARS,
  MAX_OPAQUE_PNG_DECODED_BYTES,
  MAX_OPAQUE_PNG_DIMENSION,
  MAX_OPAQUE_PNG_PIXELS,
} from "../dist/hooks/shared/provider-attachment-data-url.js"
import {
  collisionPngBuffer,
  GOOGLE_KEY_COLLISION,
  pngBuffer,
  pngChunk,
  pngDataUrl,
} from "./fixtures/provider-boundary-fixtures.mjs"

test("canonical PNG attachment accepts a transport-level Google-key collision", () => {
  const url = pngDataUrl(collisionPngBuffer())
  assert.equal(url.includes(GOOGLE_KEY_COLLISION), true)
  assert.equal(isCanonicalStructurallyValidPngDataUrl(url), true)
})

test("PNG container validation rejects malformed framing and critical structure", () => {
  const valid = collisionPngBuffer()
  const badCrc = Buffer.from(valid)
  badCrc[45] ^= 1

  assert.equal(isStructurallyValidPngContainer(valid), true)
  assert.equal(isStructurallyValidPngContainer(badCrc), false)
  assert.equal(isStructurallyValidPngContainer(valid.subarray(0, -12)), false)
  assert.equal(
    isStructurallyValidPngContainer(
      pngBuffer({ beforeImageData: [pngChunk("ABCD", Buffer.from([1]))] }),
    ),
    false,
  )
  assert.equal(
    isStructurallyValidPngContainer(
      pngBuffer({ beforeImageData: [pngChunk("rust", Buffer.from([1]))] }),
    ),
    false,
  )
  assert.equal(
    isStructurallyValidPngContainer(
      pngBuffer({
        beforeImageData: [pngChunk("IDAT", Buffer.from([1]))],
        afterImageData: [pngChunk("ruSt"), pngChunk("IDAT", Buffer.from([2]))],
      }),
    ),
    false,
  )
  assert.equal(isStructurallyValidPngContainer(pngBuffer({ bitDepth: 4 })), false)
})

test("canonical data URL validation rejects alternate and appended encodings", () => {
  const url = pngDataUrl(collisionPngBuffer())
  const plusIndex = url.indexOf("+")
  assert.equal(plusIndex > 0, true)
  assert.equal(
    isCanonicalStructurallyValidPngDataUrl(`data:image/jpeg;base64,${url.split(",")[1]}`),
    false,
  )
  assert.equal(
    isCanonicalStructurallyValidPngDataUrl(`${url.slice(0, plusIndex)}-${url.slice(plusIndex + 1)}`),
    false,
  )
  assert.equal(isCanonicalStructurallyValidPngDataUrl(`${url.slice(0, -1)}\n=`), false)
  assert.equal(isCanonicalStructurallyValidPngDataUrl(url.slice(0, -1)), false)
  assert.equal(isCanonicalStructurallyValidPngDataUrl(`${url}AAAA`), false)
  assert.equal(
    isCanonicalStructurallyValidPngDataUrl(
      `data:image/png;base64,${"A".repeat(MAX_OPAQUE_PNG_DATA_URL_CHARS)}`,
    ),
    false,
  )
})

test("container limits enforce dimensions, pixels, and chunk count", () => {
  assert.equal(
    isStructurallyValidPngContainer(pngBuffer({ width: MAX_OPAQUE_PNG_DIMENSION })),
    true,
  )
  assert.equal(
    isStructurallyValidPngContainer(pngBuffer({ width: MAX_OPAQUE_PNG_DIMENSION + 1 })),
    false,
  )
  const pixelWidth = 10_000
  const pixelHeight = Math.floor(MAX_OPAQUE_PNG_PIXELS / pixelWidth)
  assert.equal(
    isStructurallyValidPngContainer(pngBuffer({ width: pixelWidth, height: pixelHeight })),
    true,
  )
  assert.equal(
    isStructurallyValidPngContainer(
      pngBuffer({ width: pixelWidth, height: pixelHeight + 1 }),
    ),
    false,
  )

  const exactAncillaryCount = MAX_OPAQUE_PNG_CHUNKS - 3
  const exactChunks = Array.from({ length: exactAncillaryCount }, () => pngChunk("ruSt"))
  assert.equal(
    isStructurallyValidPngContainer(pngBuffer({ beforeImageData: exactChunks })),
    true,
  )
  assert.equal(
    isStructurallyValidPngContainer(
      pngBuffer({ beforeImageData: [...exactChunks, pngChunk("ruSt")] }),
    ),
    false,
  )
})

test("container accepts CRC-valid opaque IDAT without claiming decoded image validity", () => {
  assert.equal(
    isStructurallyValidPngContainer(pngBuffer({ imageData: Buffer.from([1, 2, 3]) })),
    true,
  )
})

test("container decoded-byte limit is exact", () => {
  const fixedLength = pngBuffer({ beforeImageData: [pngChunk("ruSt")] }).length
  const payloadLength = MAX_OPAQUE_PNG_DECODED_BYTES - fixedLength
  const nearLimit = pngBuffer({
    beforeImageData: [pngChunk("ruSt", Buffer.alloc(payloadLength))],
  })
  assert.equal(nearLimit.length, MAX_OPAQUE_PNG_DECODED_BYTES)
  assert.equal(isStructurallyValidPngContainer(nearLimit), true)

  const oneOver = Buffer.concat([nearLimit, Buffer.from([0])])
  assert.equal(oneOver.length, MAX_OPAQUE_PNG_DECODED_BYTES + 1)
  assert.equal(isStructurallyValidPngContainer(oneOver), false)
})


test("provider attachment contract pins MIME types and resource caps", () => {
  assert.equal(MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS, 16 * 1024 * 1024)
  assert.equal(MAX_OPAQUE_ATTACHMENT_DECODED_BYTES, 12 * 1024 * 1024)
  assert.equal(MAX_OPAQUE_PNG_DATA_URL_CHARS, 16 * 1024 * 1024)
  assert.equal(MAX_OPAQUE_PNG_DECODED_BYTES, 12 * 1024 * 1024)
  assert.deepEqual(OPAQUE_PROVIDER_ATTACHMENT_MIME_TYPES, [
    "image/png",
    "image/jpeg",
    "application/pdf",
  ])
})

test("canonical provider attachment parser returns exact payload bounds", () => {
  const fixtures = [
    ["image/png", collisionPngBuffer()],
    ["image/jpeg", Buffer.from([0xff, 0xd8, 0xff, 0xd9])],
    ["application/pdf", Buffer.from("%PDF-1.7\n%%EOF\n", "ascii")],
  ]
  for (const [mime, bytes] of fixtures) {
    const prefix = `data:${mime};base64,`
    const url = `${prefix}${bytes.toString("base64")}`
    assert.deepEqual(parseCanonicalProviderAttachmentDataUrl(url, mime), {
      mime,
      payloadStart: prefix.length,
      payloadEnd: url.length,
      decodedBytes: bytes.length,
    })
  }
})

test("provider attachment parser rejects MIME and Base64 ambiguity", () => {
  const payload = Buffer.from([0xff, 0xd8, 0xff, 0xd9]).toString("base64")
  assert.equal(
    parseCanonicalProviderAttachmentDataUrl(`data:image/jpeg;base64,${payload}`, "image/png"),
    null,
  )
  assert.equal(
    parseCanonicalProviderAttachmentDataUrl(`data:image/jpg;base64,${payload}`, "image/jpg"),
    null,
  )
  assert.equal(
    parseCanonicalProviderAttachmentDataUrl(
      `data:image/jpeg;charset=utf-8;base64,${payload}`,
      "image/jpeg",
    ),
    null,
  )
  assert.equal(
    parseCanonicalProviderAttachmentDataUrl(`data:image/gif;base64,${payload}`, "image/gif"),
    null,
  )
  assert.equal(parseCanonicalProviderAttachmentDataUrl("data:image/jpeg;base64,", "image/jpeg"), null)
  assert.equal(
    parseCanonicalProviderAttachmentDataUrl(
      `data:image/jpeg;base64,${payload.slice(0, -1)}`,
      "image/jpeg",
    ),
    null,
  )
  assert.equal(
    parseCanonicalProviderAttachmentDataUrl(
      `data:image/jpeg;base64,${payload.replace("/", "_")}`,
      "image/jpeg",
    ),
    null,
  )
})

test("provider attachment URL limit is exact and bounded", () => {
  const mime = "application/pdf"
  const prefix = `data:${mime};base64,`
  const payloadChars =
    Math.floor((MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS - prefix.length) / 4) * 4
  const decodedBytes = (payloadChars / 4) * 3
  const atLimit = `${prefix}${Buffer.alloc(decodedBytes).toString("base64")}`
  assert.equal(atLimit.length, MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS)
  assert.notEqual(parseCanonicalProviderAttachmentDataUrl(atLimit, mime), null)

  const oneOver = `${prefix}${Buffer.alloc(decodedBytes + 3).toString("base64")}`
  assert.equal(oneOver.length, MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS + 4)
  assert.equal(parseCanonicalProviderAttachmentDataUrl(oneOver, mime), null)
})
