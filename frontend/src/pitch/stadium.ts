import * as THREE from 'three'

function box(parent: THREE.Object3D, size: [number, number, number], at: [number, number, number], material: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material)
  mesh.position.set(...at)
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

function fieldTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = 2100; canvas.height = 1360
  const ctx = canvas.getContext('2d')!
  for (let i = 0; i < 14; i++) {
    ctx.fillStyle = i % 2 ? '#397e3c' : '#438d43'
    ctx.fillRect(i * 150, 0, 150, 1360)
  }
  // Deterministic fine turf variation; no image or stadium assets are downloaded.
  let seed = 741
  for (let i = 0; i < 95000; i++) {
    seed = (seed * 1664525 + 1013904223) >>> 0
    const x = seed % 2100
    seed = (seed * 1664525 + 1013904223) >>> 0
    const y = seed % 1360
    ctx.fillStyle = i % 2 ? '#ffffff0b' : '#102c1410'
    ctx.fillRect(x, y, 1, 3)
  }
  ctx.scale(20, 20)
  ctx.strokeStyle = '#e5eee0'; ctx.fillStyle = '#e5eee0'; ctx.lineWidth = .12
  ctx.strokeRect(.08, .08, 104.84, 67.84)
  ctx.beginPath(); ctx.moveTo(52.5, 0); ctx.lineTo(52.5, 68); ctx.stroke()
  ctx.beginPath(); ctx.arc(52.5, 34, 9.15, 0, Math.PI * 2); ctx.stroke()
  for (const x of [0, 105]) {
    const left = x === 0
    ctx.strokeRect(left ? 0 : 88.5, 13.84, 16.5, 40.32)
    ctx.strokeRect(left ? 0 : 99.5, 24.84, 5.5, 18.32)
    const penalty = left ? 11 : 94
    ctx.beginPath(); ctx.arc(penalty, 34, .16, 0, Math.PI * 2); ctx.fill()
    const angle = Math.acos(5.5 / 9.15)
    ctx.beginPath()
    ctx.arc(penalty, 34, 9.15, left ? -angle : Math.PI - angle, left ? angle : Math.PI + angle)
    ctx.stroke()
  }
  for (const [x, y, start] of [[0, 0, 0], [105, 0, Math.PI / 2], [105, 68, Math.PI], [0, 68, Math.PI * 1.5]]) {
    ctx.beginPath(); ctx.arc(x, y, 1, start, start + Math.PI / 2); ctx.stroke()
  }
  ctx.beginPath(); ctx.arc(52.5, 34, .16, 0, Math.PI * 2); ctx.fill()
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.anisotropy = 8
  return texture
}

function createGoal(side: number): THREE.Group {
  const goal = new THREE.Group()
  goal.position.x = side * 52.5
  const white = new THREE.MeshStandardMaterial({ color: '#eff2ed', roughness: .4 })
  const net = new THREE.LineBasicMaterial({ color: '#cbd7d8', transparent: true, opacity: .4 })
  const netPoints: THREE.Vector3[] = []
  const netLine = (points: THREE.Vector3[]) => {
    for (let i = 1; i < points.length; i++) netPoints.push(points[i - 1], points[i])
  }
  const pipe = (from: THREE.Vector3, to: THREE.Vector3, radius = .065) => {
    const direction = to.clone().sub(from)
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, direction.length(), 8), white)
    mesh.position.copy(from).add(to).multiplyScalar(.5)
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize())
    mesh.castShadow = true
    goal.add(mesh)
  }
  for (const z of [-3.66, 3.66]) {
    pipe(new THREE.Vector3(0, 0, z), new THREE.Vector3(0, 2.44, z))
    pipe(new THREE.Vector3(0, 2.44, z), new THREE.Vector3(side * 2.3, 1.85, z), .035)
    pipe(new THREE.Vector3(side * 2.3, 1.85, z), new THREE.Vector3(side * 2.3, 0, z), .035)
    pipe(new THREE.Vector3(0, .04, z), new THREE.Vector3(side * 2.3, .04, z), .035)
    for (let h = 0; h <= 2.44; h += .24) {
      netLine([new THREE.Vector3(0, h, z), new THREE.Vector3(side * 2.3, h * .76, z)])
    }
    for (let d = 0; d <= 2.3; d += .23) {
      netLine([new THREE.Vector3(side * d, .04, z), new THREE.Vector3(side * d, 2.44 * (1 - .24 * d / 2.3), z)])
    }
  }
  pipe(new THREE.Vector3(0, 2.44, -3.66), new THREE.Vector3(0, 2.44, 3.66))
  pipe(new THREE.Vector3(side * 2.3, 1.85, -3.66), new THREE.Vector3(side * 2.3, 1.85, 3.66), .035)
  for (let z = -3.66; z <= 3.66; z += .24) {
    netLine([new THREE.Vector3(0, 2.44, z), new THREE.Vector3(side * 2.3, 1.85, z), new THREE.Vector3(side * 2.3, .04, z)])
  }
  for (let h = 0; h <= 1.86; h += .23) {
    netLine([new THREE.Vector3(side * 2.3, h, -3.66), new THREE.Vector3(side * 2.3, h, 3.66)])
  }
  for (let d = 0; d < 2.3; d += .23) {
    netLine([new THREE.Vector3(side * d, 2.44 * (1 - .24 * d / 2.3), -3.66), new THREE.Vector3(side * d, 2.44 * (1 - .24 * d / 2.3), 3.66)])
  }
  goal.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(netPoints), net))
  return goal
}

function advertisingTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = 2048; canvas.height = 128
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#0b1923'; ctx.fillRect(0, 0, 2048, 128)
  ctx.fillStyle = '#d2f57a'; ctx.font = 'bold 72px sans-serif'; ctx.textBaseline = 'middle'
  ctx.fillText('KELLAN', 45, 67)
  ctx.fillStyle = '#e1e8e4'; ctx.font = '34px sans-serif'; ctx.fillText('SEE THE PLAY. TRUST THE STORY.', 460, 67)
  ctx.fillStyle = '#d2f57a'; ctx.fillText('MERIDIAN LEAGUE', 1520, 67)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

export function buildStadium(scene: THREE.Scene) {
  scene.background = new THREE.Color('#142332')
  scene.fog = new THREE.Fog('#142332', 130, 260)
  scene.add(new THREE.HemisphereLight('#e1eeff', '#405342', 2.5))
  const sun = new THREE.DirectionalLight('#fff4da', 3.4)
  sun.position.set(-28, 65, -38)
  sun.castShadow = true
  sun.shadow.mapSize.set(2048, 2048)
  Object.assign(sun.shadow.camera, { left: -74, right: 74, top: 58, bottom: -58, near: 1, far: 160 })
  sun.shadow.bias = -.0003; sun.shadow.normalBias = .05
  scene.add(sun)
  const fill = new THREE.DirectionalLight('#aecfff', 1.2)
  fill.position.set(30, 30, 40); scene.add(fill)

  const concrete = new THREE.MeshStandardMaterial({ color: '#253540', roughness: .95 })
  const edge = new THREE.MeshStandardMaterial({ color: '#101c26', roughness: .85 })
  box(scene, [190, .5, 144], [0, -.8, 0], edge)
  box(scene, [144, .3, 106], [0, -.35, 0], concrete)
  const apron = new THREE.Mesh(new THREE.PlaneGeometry(121, 82), new THREE.MeshStandardMaterial({ color: '#326b38', roughness: 1 }))
  apron.rotation.x = -Math.PI / 2; apron.position.y = -.015; apron.receiveShadow = true; scene.add(apron)
  const turf = new THREE.Mesh(new THREE.PlaneGeometry(105, 68), new THREE.MeshStandardMaterial({ map: fieldTexture(), roughness: 1 }))
  turf.rotation.x = -Math.PI / 2; turf.receiveShadow = true; scene.add(turf)
  scene.add(createGoal(-1), createGoal(1))

  const boards = new THREE.MeshStandardMaterial({ map: advertisingTexture(), emissive: '#bacacf', emissiveIntensity: .22, roughness: .7 })
  for (const side of [-1, 1]) {
    for (let section = 0; section < 4; section++) {
      box(scene, [26.8, 1.05, .28], [-40.5 + section * 27, .53, side * 38.5], boards)
    }
    for (const z of [-23, 23]) box(scene, [.28, 1.05, 24], [side * 58.5, .53, z], boards)
  }

  const crowdPoints: THREE.Vector3[] = []
  const stand = new THREE.Group()
  const seat = new THREE.MeshStandardMaterial({ color: '#344552', roughness: .9 })
  for (let row = 0; row < 11; row++) {
    const height = .45 + row * .65
    for (const side of [-1, 1]) {
      const z = side * (43 + row * 1.3)
      box(stand, [132, .65, 1.35], [0, height, z], row % 3 === 0 ? seat : concrete)
      for (let col = -64; col < 65; col += 1.25) {
        if (Math.abs(col % 22) < 1.4) continue
        crowdPoints.push(new THREE.Vector3(col, height + .75, z))
      }
      const x = side * (63 + row * 1.3)
      box(stand, [1.35, .65, 82], [x, height, 0], row % 3 === 0 ? seat : concrete)
      for (let col = -39; col < 40; col += 1.25) {
        if (Math.abs(col % 18) < 1.3) continue
        crowdPoints.push(new THREE.Vector3(x, height + .75, col))
      }
    }
  }
  const crowd = new THREE.InstancedMesh(new THREE.SphereGeometry(.32, 5, 4), new THREE.MeshStandardMaterial({ roughness: 1 }), crowdPoints.length)
  const dummy = new THREE.Object3D()
  const palette = ['#7697b4', '#b3b8ac', '#283947', '#7a4c42', '#c7b389', '#3a6875']
  crowdPoints.forEach((point, i) => {
    dummy.position.copy(point); dummy.scale.set(.8, 1.4 + (i % 3) * .1, .8); dummy.updateMatrix()
    crowd.setMatrixAt(i, dummy.matrix)
    crowd.setColorAt(i, new THREE.Color(palette[(i * 17 + Math.floor(i / 7)) % palette.length]))
  })
  stand.add(crowd)
  scene.add(stand)

  const steel = new THREE.MeshStandardMaterial({ color: '#7d8a96', metalness: .65, roughness: .5 })
  const lamp = new THREE.MeshStandardMaterial({ color: '#e8f4ff', emissive: '#c8e4ff', emissiveIntensity: 2 })
  for (const x of [-61, 61]) for (const z of [-43, 43]) {
    box(scene, [.4, 24, .4], [x, 12, z], steel)
    box(scene, [6, .18, 2.2], [x, 24, z], edge)
    for (let i = 0; i < 6; i++) box(scene, [.68, .12, 1.7], [x - 2.5 + i, 23.85, z], lamp)
  }
  // A far-side canopy frames the pitch without hiding play from low cameras.
  box(scene, [145, .4, 15], [0, 15, -55], edge)
  for (let x = -65; x <= 65; x += 13) box(scene, [.3, 8, .3], [x, 11, -61], steel)

  const flagMaterial = new THREE.MeshStandardMaterial({ color: '#eaf575', side: THREE.DoubleSide })
  for (const x of [-52.5, 52.5]) for (const z of [-34, 34]) {
    box(scene, [.035, 1.5, .035], [x, .75, z], steel)
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(.55, .32), flagMaterial)
    flag.position.set(x + .27, 1.3, z); scene.add(flag)
  }
}

export function createBall(): THREE.Group {
  const ball = new THREE.Group()
  const white = new THREE.MeshStandardMaterial({ color: '#fffef0', roughness: .57 })
  const black = new THREE.MeshStandardMaterial({ color: '#15232c', roughness: .7, side: THREE.DoubleSide })
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(.24, 24, 16), white)
  sphere.castShadow = true; ball.add(sphere)
  const positions = new THREE.IcosahedronGeometry(1, 0)
  const vertices = positions.getAttribute('position')
  const unique = new Set<string>()
  for (let i = 0; i < vertices.count; i++) {
    const normal = new THREE.Vector3().fromBufferAttribute(vertices, i).normalize()
    const key = normal.toArray().map(v => v.toFixed(3)).join(',')
    if (unique.has(key)) continue
    unique.add(key)
    const patch = new THREE.Mesh(new THREE.CircleGeometry(.082, 5), black)
    patch.position.copy(normal).multiplyScalar(.242)
    patch.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal)
    ball.add(patch)
  }
  positions.dispose()
  ball.position.y = .25
  return ball
}
