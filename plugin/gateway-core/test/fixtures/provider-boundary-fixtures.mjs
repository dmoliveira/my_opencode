import { crc32, deflateSync } from "node:zlib"

export const GOOGLE_KEY_COLLISION = `AIza${"A".repeat(20)}`

const PNG_SIGNATURE_BYTES = Object.freeze([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
])

export function pngChunk(type, data = Buffer.alloc(0)) {
  const typeBytes = Buffer.from(type, "ascii")
  const header = Buffer.alloc(4)
  header.writeUInt32BE(data.length)
  const checksum = Buffer.alloc(4)
  checksum.writeUInt32BE(crc32(Buffer.concat([typeBytes, data])) >>> 0)
  return Buffer.concat([header, typeBytes, data, checksum])
}

export function pngBuffer({
  width = 1,
  height = 1,
  bitDepth = 8,
  colorType = 6,
  beforeImageData = [],
  imageData = deflateSync(Buffer.from([0, 0, 0, 0, 255])),
  afterImageData = [],
} = {}) {
  const headerData = Buffer.alloc(13)
  headerData.writeUInt32BE(width, 0)
  headerData.writeUInt32BE(height, 4)
  headerData[8] = bitDepth
  headerData[9] = colorType
  return Buffer.concat([
    Buffer.from(PNG_SIGNATURE_BYTES),
    pngChunk("IHDR", headerData),
    ...beforeImageData,
    pngChunk("IDAT", imageData),
    ...afterImageData,
    pngChunk("IEND"),
  ])
}

export function collisionPngBuffer(options = {}) {
  const collisionBytes = Buffer.from(GOOGLE_KEY_COLLISION, "base64")
  return pngBuffer({
    ...options,
    beforeImageData: [
      pngChunk("ruSt", Buffer.concat([Buffer.from([0]), collisionBytes])),
      ...(options.beforeImageData ?? []),
    ],
  })
}

export function pngDataUrl(bytes = collisionPngBuffer()) {
  return `data:image/png;base64,${bytes.toString("base64")}`
}

export function collisionBase64Payload(prefix, suffix) {
  return Buffer.concat([
    prefix,
    Buffer.from(GOOGLE_KEY_COLLISION, "base64"),
    suffix,
  ]).toString("base64")
}

export function attachmentCollisionFixtures() {
  const png = collisionPngBuffer()
  const jpegPayload = collisionBase64Payload(
    Buffer.from([0xff, 0xd8, 0xff]),
    Buffer.from([0xff, 0xd9]),
  )
  const pdfPayload = collisionBase64Payload(
    Buffer.from("%PDF-1.7\n", "ascii"),
    Buffer.from("\n%%EOF\n", "ascii"),
  )
  return [
    {
      id: "png",
      mime: "image/png",
      bytes: png,
      url: pngDataUrl(png),
    },
    {
      id: "jpeg",
      mime: "image/jpeg",
      bytes: Buffer.from(jpegPayload, "base64"),
      url: `data:image/jpeg;base64,${jpegPayload}`,
    },
    {
      id: "pdf",
      mime: "application/pdf",
      bytes: Buffer.from(pdfPayload, "base64"),
      url: `data:application/pdf;base64,${pdfPayload}`,
    },
  ]
}
