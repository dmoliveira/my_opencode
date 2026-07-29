import assert from "node:assert/strict"
import { deflateSync, crc32 } from "node:zlib"
import test from "node:test"

import {
  isCanonicalStructurallyValidPngDataUrl,
  isStructurallyValidPngContainer,
  MAX_OPAQUE_PNG_CHUNKS,
  MAX_OPAQUE_PNG_DATA_URL_CHARS,
  MAX_OPAQUE_PNG_DECODED_BYTES,
  MAX_OPAQUE_PNG_DIMENSION,
  MAX_OPAQUE_PNG_PIXELS,
} from "../dist/hooks/shared/provider-attachment-data-url.js"

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
const GOOGLE_COLLISION = `AIza${"A".repeat(20)}`

function chunk(type, data = Buffer.alloc(0)) {
  const typeBytes = Buffer.from(type, "ascii")
  const header = Buffer.alloc(4)
  header.writeUInt32BE(data.length)
  const checksum = Buffer.alloc(4)
  checksum.writeUInt32BE(crc32(Buffer.concat([typeBytes, data])) >>> 0)
  return Buffer.concat([header, typeBytes, data, checksum])
}

function header({ width = 1, height = 1, bitDepth = 8, colorType = 6 } = {}) {
  const data = Buffer.alloc(13)
  data.writeUInt32BE(width, 0)
  data.writeUInt32BE(height, 4)
  data[8] = bitDepth
  data[9] = colorType
  data[10] = 0
  data[11] = 0
  data[12] = 0
  return chunk("IHDR", data)
}

function pngBuffer({
  width = 1,
  height = 1,
  bitDepth = 8,
  colorType = 6,
  beforeImageData = [],
  imageData = deflateSync(Buffer.from([0, 0, 0, 0, 255])),
  afterImageData = [],
} = {}) {
  return Buffer.concat([
    SIGNATURE,
    header({ width, height, bitDepth, colorType }),
    ...beforeImageData,
    chunk("IDAT", imageData),
    ...afterImageData,
    chunk("IEND"),
  ])
}

function collisionPngBuffer(options = {}) {
  const collisionBytes = Buffer.from(GOOGLE_COLLISION, "base64")
  assert.equal(collisionBytes.toString("base64"), GOOGLE_COLLISION)
  return pngBuffer({
    ...options,
    beforeImageData: [
      chunk("ruSt", Buffer.concat([Buffer.from([0]), collisionBytes])),
      ...(options.beforeImageData ?? []),
    ],
  })
}

function dataUrl(bytes) {
  return `data:image/png;base64,${bytes.toString("base64")}`
}

test("canonical PNG attachment accepts a transport-level Google-key collision", () => {
  const url = dataUrl(collisionPngBuffer())
  assert.equal(url.includes(GOOGLE_COLLISION), true)
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
      pngBuffer({ beforeImageData: [chunk("ABCD", Buffer.from([1]))] }),
    ),
    false,
  )
  assert.equal(
    isStructurallyValidPngContainer(
      pngBuffer({ beforeImageData: [chunk("rust", Buffer.from([1]))] }),
    ),
    false,
  )
  assert.equal(
    isStructurallyValidPngContainer(
      pngBuffer({
        beforeImageData: [chunk("IDAT", Buffer.from([1]))],
        afterImageData: [chunk("ruSt"), chunk("IDAT", Buffer.from([2]))],
      }),
    ),
    false,
  )
  assert.equal(isStructurallyValidPngContainer(pngBuffer({ bitDepth: 4 })), false)
})

test("canonical data URL validation rejects alternate and appended encodings", () => {
  const url = dataUrl(collisionPngBuffer())
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
  const exactChunks = Array.from({ length: exactAncillaryCount }, () => chunk("ruSt"))
  assert.equal(
    isStructurallyValidPngContainer(pngBuffer({ beforeImageData: exactChunks })),
    true,
  )
  assert.equal(
    isStructurallyValidPngContainer(
      pngBuffer({ beforeImageData: [...exactChunks, chunk("ruSt")] }),
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

test("near-limit container validation remains bounded", () => {
  const fixedLength = pngBuffer({ beforeImageData: [chunk("ruSt")] }).length
  const payloadLength = MAX_OPAQUE_PNG_DECODED_BYTES - fixedLength
  const nearLimit = pngBuffer({ beforeImageData: [chunk("ruSt", Buffer.alloc(payloadLength))] })
  assert.equal(nearLimit.length, MAX_OPAQUE_PNG_DECODED_BYTES)

  isStructurallyValidPngContainer(nearLimit)
  const durations = []
  for (let index = 0; index < 5; index += 1) {
    const start = performance.now()
    assert.equal(isStructurallyValidPngContainer(nearLimit), true)
    durations.push(performance.now() - start)
  }
  durations.sort((left, right) => left - right)
  assert.equal(durations.at(-1) < 2_000, true)

  const oneOver = Buffer.concat([nearLimit, Buffer.from([0])])
  assert.equal(oneOver.length, MAX_OPAQUE_PNG_DECODED_BYTES + 1)
  assert.equal(isStructurallyValidPngContainer(oneOver), false)
})
