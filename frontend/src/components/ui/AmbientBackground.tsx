import { useEffect, useRef } from 'react'

/**
 * The dashboard's signature background: a slow particle field drifting
 * behind a fixed radial gradient mesh, rendered on one <canvas> with a
 * single requestAnimationFrame loop. Deliberately not WebGL -- a few dozen
 * circles updated per frame is not a workload that benefits from a shader
 * pipeline, and 2D canvas has no GPU-driver surface to fail on.
 *
 * Respects prefers-reduced-motion (renders one static frame and stops) and
 * pauses entirely when the tab is hidden, so it never spends a laptop's
 * battery animating something nobody is looking at.
 */
export function AmbientBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    let width = 0
    let height = 0
    let mouseX = 0.5
    let mouseY = 0.5

    interface Particle {
      x: number
      y: number
      vx: number
      vy: number
      r: number
      hue: 'primary' | 'secondary'
    }

    const PARTICLE_COUNT = 46
    const particles: Particle[] = Array.from({ length: PARTICLE_COUNT }, () => ({
      x: Math.random(),
      y: Math.random(),
      vx: (Math.random() - 0.5) * 0.00012,
      vy: (Math.random() - 0.5) * 0.00012,
      r: Math.random() * 1.4 + 0.4,
      hue: Math.random() > 0.6 ? 'secondary' : 'primary',
    }))

    function resize() {
      if (!canvas) return
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    function handlePointerMove(e: PointerEvent) {
      mouseX = e.clientX / window.innerWidth
      mouseY = e.clientY / window.innerHeight
    }

    function draw() {
      if (!ctx) return
      ctx.clearRect(0, 0, width, height)

      // Parallax drifts opposite the pointer, subtly -- depth, not a
      // cursor-follower. Capped to a few px so it never fights readability.
      const parallaxX = (mouseX - 0.5) * 24
      const parallaxY = (mouseY - 0.5) * 24

      const gradient = ctx.createRadialGradient(
        width * 0.2 + parallaxX,
        height * 0.15 + parallaxY,
        0,
        width * 0.2,
        height * 0.15,
        width * 0.7,
      )
      gradient.addColorStop(0, 'rgba(79, 125, 255, 0.10)')
      gradient.addColorStop(1, 'rgba(79, 125, 255, 0)')
      ctx.fillStyle = gradient
      ctx.fillRect(0, 0, width, height)

      const gradient2 = ctx.createRadialGradient(
        width * 0.85 - parallaxX,
        height * 0.75 - parallaxY,
        0,
        width * 0.85,
        height * 0.75,
        width * 0.6,
      )
      gradient2.addColorStop(0, 'rgba(167, 107, 255, 0.09)')
      gradient2.addColorStop(1, 'rgba(167, 107, 255, 0)')
      ctx.fillStyle = gradient2
      ctx.fillRect(0, 0, width, height)

      for (const p of particles) {
        if (!reduceMotion) {
          p.x += p.vx
          p.y += p.vy
          if (p.x < -0.05) p.x = 1.05
          if (p.x > 1.05) p.x = -0.05
          if (p.y < -0.05) p.y = 1.05
          if (p.y > 1.05) p.y = -0.05
        }
        const px = p.x * width + parallaxX * 0.4
        const py = p.y * height + parallaxY * 0.4
        ctx.beginPath()
        ctx.arc(px, py, p.r, 0, Math.PI * 2)
        ctx.fillStyle =
          p.hue === 'primary' ? 'rgba(148, 178, 255, 0.35)' : 'rgba(199, 165, 255, 0.3)'
        ctx.fill()
      }
    }

    let frame = 0
    let running = true
    function loop() {
      if (!running) return
      draw()
      if (!reduceMotion) frame = requestAnimationFrame(loop)
    }

    function handleVisibility() {
      if (document.hidden) {
        running = false
        cancelAnimationFrame(frame)
      } else {
        running = true
        loop()
      }
    }

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(canvas)
    resize()
    window.addEventListener('pointermove', handlePointerMove, { passive: true })
    document.addEventListener('visibilitychange', handleVisibility)
    loop()

    return () => {
      running = false
      cancelAnimationFrame(frame)
      resizeObserver.disconnect()
      window.removeEventListener('pointermove', handlePointerMove)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-bg">
      <canvas ref={canvasRef} className="h-full w-full" />
      {/* Subtle grid + noise, CSS-only -- no per-frame cost. */}
      <div
        className="absolute inset-0 opacity-[0.035]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(148,163,255,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,255,0.5) 1px, transparent 1px)',
          backgroundSize: '64px 64px',
        }}
      />
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-bg" />
    </div>
  )
}
