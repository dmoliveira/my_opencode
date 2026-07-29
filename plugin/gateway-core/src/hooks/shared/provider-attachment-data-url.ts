export const OPAQUE_PROVIDER_ATTACHMENT_MIME_TYPES = [
  "image/png",
  "image/jpeg",
  "application/pdf",
] as const

export type OpaqueProviderAttachmentMime =
  (typeof OPAQUE_PROVIDER_ATTACHMENT_MIME_TYPES)[number]

export interface CanonicalProviderAttachmentDataUrl {
  mime: OpaqueProviderAttachmentMime
  payloadStart: number
  payloadEnd: number
  decodedBytes: number
}

export const MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS = 16 * 1024 * 1024
export const MAX_OPAQUE_ATTACHMENT_DECODED_BYTES = 12 * 1024 * 1024
export const MAX_OPAQUE_PNG_DATA_URL_CHARS = MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS
export const MAX_OPAQUE_PNG_DECODED_BYTES = MAX_OPAQUE_ATTACHMENT_DECODED_BYTES
export const MAX_OPAQUE_PNG_CHUNKS = 16_384
export const MAX_OPAQUE_PNG_DIMENSION = 32_768
export const MAX_OPAQUE_PNG_PIXELS = 100_000_000

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
function isBase64Alphabet(value: number): boolean {
  return (
    (value >= 0x41 && value <= 0x5a) ||
    (value >= 0x61 && value <= 0x7a) ||
    (value >= 0x30 && value <= 0x39) ||
    value === 0x2b ||
    value === 0x2f
  )
}

function isCanonicalBase64Text(value: string): boolean {
  if (!value || value.length % 4 !== 0) return false
  let padding = 0
  if (value.endsWith("=")) padding += 1
  if (value.endsWith("==")) padding += 1
  const contentEnd = value.length - padding
  for (let index = 0; index < contentEnd; index += 1) {
    if (!isBase64Alphabet(value.charCodeAt(index))) return false
  }
  for (let index = contentEnd; index < value.length; index += 1) {
    if (value.charCodeAt(index) !== 0x3d) return false
  }
  return true
}
const KNOWN_CRITICAL_CHUNKS = new Set(["IHDR", "PLTE", "IDAT", "IEND"])

const PNG_CRC_TABLE = Uint32Array.from({ length: 256 }, (_, index) => {
  let value = index
  for (let bit = 0; bit < 8; bit += 1) {
    value = (value & 1) !== 0 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
  }
  return value >>> 0
})

function pngCrc32(bytes: Buffer, start: number, end: number): number {
  let crc = 0xffffffff
  for (let index = start; index < end; index += 1) {
    crc = PNG_CRC_TABLE[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ 0xffffffff) >>> 0
}

function isAsciiLetter(value: number): boolean {
  return (value >= 0x41 && value <= 0x5a) || (value >= 0x61 && value <= 0x7a)
}

function validBitDepth(colorType: number, bitDepth: number): boolean {
  if (colorType === 0) return [1, 2, 4, 8, 16].includes(bitDepth)
  if (colorType === 2) return bitDepth === 8 || bitDepth === 16
  if (colorType === 3) return [1, 2, 4, 8].includes(bitDepth)
  if (colorType === 4 || colorType === 6) return bitDepth === 8 || bitDepth === 16
  return false
}

export function isStructurallyValidPngContainer(bytes: Buffer): boolean {
  try {
    if (
      bytes.length < PNG_SIGNATURE.length + 12 + 12 ||
      bytes.length > MAX_OPAQUE_PNG_DECODED_BYTES ||
      !bytes.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE)
    ) {
      return false
    }

    let offset = PNG_SIGNATURE.length
    let chunkCount = 0
    let colorType = -1
    let bitDepth = -1
    let seenHeader = false
    let seenPalette = false
    let seenImageData = false
    let imageDataClosed = false
    let imageDataBytes = 0

    while (offset < bytes.length) {
      if (bytes.length - offset < 12) return false
      chunkCount += 1
      if (chunkCount > MAX_OPAQUE_PNG_CHUNKS) return false

      const length = bytes.readUInt32BE(offset)
      const typeOffset = offset + 4
      const dataOffset = typeOffset + 4
      const crcOffset = dataOffset + length
      const nextOffset = crcOffset + 4
      if (crcOffset < dataOffset || nextOffset > bytes.length) return false

      const typeBytes = bytes.subarray(typeOffset, dataOffset)
      if (
        typeBytes.length !== 4 ||
        ![...typeBytes].every(isAsciiLetter) ||
        (typeBytes[2] & 0x20) !== 0
      ) {
        return false
      }
      const type = typeBytes.toString("ascii")
      const expectedCrc = bytes.readUInt32BE(crcOffset)
      if (pngCrc32(bytes, typeOffset, crcOffset) !== expectedCrc) return false

      if (chunkCount === 1 && type !== "IHDR") return false
      if (seenImageData && type !== "IDAT") imageDataClosed = true

      if (type === "IHDR") {
        if (seenHeader || chunkCount !== 1 || length !== 13) return false
        const width = bytes.readUInt32BE(dataOffset)
        const height = bytes.readUInt32BE(dataOffset + 4)
        bitDepth = bytes[dataOffset + 8]
        colorType = bytes[dataOffset + 9]
        const compression = bytes[dataOffset + 10]
        const filter = bytes[dataOffset + 11]
        const interlace = bytes[dataOffset + 12]
        if (
          width < 1 ||
          height < 1 ||
          width > MAX_OPAQUE_PNG_DIMENSION ||
          height > MAX_OPAQUE_PNG_DIMENSION ||
          width * height > MAX_OPAQUE_PNG_PIXELS ||
          !validBitDepth(colorType, bitDepth) ||
          compression !== 0 ||
          filter !== 0 ||
          (interlace !== 0 && interlace !== 1)
        ) {
          return false
        }
        seenHeader = true
      } else if (type === "PLTE") {
        if (
          !seenHeader ||
          seenPalette ||
          seenImageData ||
          colorType === 0 ||
          colorType === 4 ||
          length < 3 ||
          length > 768 ||
          length % 3 !== 0 ||
          length / 3 > 2 ** bitDepth
        ) {
          return false
        }
        seenPalette = true
      } else if (type === "IDAT") {
        if (!seenHeader || imageDataClosed || length === 0) return false
        if (colorType === 3 && !seenPalette) return false
        seenImageData = true
        imageDataBytes += length
        if (imageDataBytes > MAX_OPAQUE_PNG_DECODED_BYTES) return false
      } else if (type === "IEND") {
        return (
          seenHeader &&
          seenImageData &&
          imageDataBytes > 0 &&
          (colorType !== 3 || seenPalette) &&
          length === 0 &&
          nextOffset === bytes.length
        )
      } else if ((typeBytes[0] & 0x20) === 0 && !KNOWN_CRITICAL_CHUNKS.has(type)) {
        return false
      }

      offset = nextOffset
    }
    return false
  } catch {
    return false
  }
}

export function parseCanonicalProviderAttachmentDataUrl(
  value: string,
  expectedMime: string,
): CanonicalProviderAttachmentDataUrl | null {
  try {
    if (
      !OPAQUE_PROVIDER_ATTACHMENT_MIME_TYPES.includes(
        expectedMime as OpaqueProviderAttachmentMime,
      ) ||
      value.length > MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS
    ) {
      return null
    }
    const mime = expectedMime as OpaqueProviderAttachmentMime
    const prefix = `data:${mime};base64,`
    if (!value.startsWith(prefix)) return null

    const payload = value.slice(prefix.length)
    if (!isCanonicalBase64Text(payload)) return null
    const decoded = Buffer.from(payload, "base64")
    if (
      decoded.length === 0 ||
      decoded.length > MAX_OPAQUE_ATTACHMENT_DECODED_BYTES ||
      decoded.toString("base64") !== payload ||
      (mime === "image/png" && !isStructurallyValidPngContainer(decoded))
    ) {
      return null
    }
    return {
      mime,
      payloadStart: prefix.length,
      payloadEnd: value.length,
      decodedBytes: decoded.length,
    }
  } catch {
    return null
  }
}

export function isCanonicalStructurallyValidPngDataUrl(value: string): boolean {
  return parseCanonicalProviderAttachmentDataUrl(value, "image/png") !== null
}
