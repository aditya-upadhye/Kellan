import { readdir, mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compileFromFile } from 'json-schema-to-typescript'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)), '..')
const schemaDir = resolve(root, 'docs/schemas')
const outputDir = resolve(root, 'frontend/src/generated')
const schemas = (await readdir(schemaDir)).filter((file) => file.endsWith('.schema.json'))

await mkdir(outputDir, { recursive: true })

for (const file of schemas) {
  const name = file.replace('.schema.json', '')
  const types = await compileFromFile(resolve(schemaDir, file), {
    bannerComment: '',
    style: { singleQuote: true, semi: false },
  })
  await writeFile(resolve(outputDir, `${name}.ts`), types)
}
