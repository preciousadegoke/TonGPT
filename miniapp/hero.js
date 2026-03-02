// --- TonGPT Hero Section Logic ---

document.addEventListener('DOMContentLoaded', () => {
    // Only init if hero landing is present
    const heroLanding = document.getElementById('hero-landing');
    if (!heroLanding) return;

    // Connect interactions to miniapp
    const launchBtns = document.querySelectorAll('.hero-launch-btn');
    launchBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            heroLanding.classList.add('hidden');
            // Allow 3D resources to be freed or just stop animation
            setTimeout(() => {
                cancelAnimationFrame(animationFrameId);
                heroLanding.style.display = 'none';
            }, 600);
        });
    });

    // 1. Background Procedural Grid & Wallet Flow Logic
    const bgCanvas = document.getElementById('bg-canvas');
    if (!bgCanvas) return;
    const bgCtx = bgCanvas.getContext('2d', { alpha: false });
    let w = window.innerWidth;
    let h = window.innerHeight;

    // Generate random nodes for the background graph overlay
    const numBgNodes = 25;
    const bgNodes = [];
    for (let i = 0; i < numBgNodes; i++) {
        bgNodes.push({
            x: Math.random() * (w * 0.45), // Keep mostly on left half
            y: h * 0.5 + Math.random() * (h * 0.5), // Lower half
            vx: (Math.random() - 0.5) * 0.4,
            vy: (Math.random() - 0.5) * 0.4,
            baseRadius: 1 + Math.random() * 2
        });
    }

    function resizeCanvases() {
        w = window.innerWidth; h = window.innerHeight;
        bgCanvas.width = w; bgCanvas.height = h;
        const hc = document.getElementById('hud-canvas');
        if (hc) {
            hc.width = w; hc.height = h;
        }

        if (camera && renderer) {
            let webGLWidth = window.innerWidth > 1024 ? w * 0.5 : w;
            camera.aspect = webGLWidth / h;
            camera.updateProjectionMatrix();
            renderer.setSize(webGLWidth, h);
        }
    }
    window.addEventListener('resize', resizeCanvases);

    function drawBackgroundGraph() {
        bgCtx.fillStyle = '#01030a';
        bgCtx.fillRect(0, 0, w, h);

        // Draw precision geometric blueprint grid
        bgCtx.lineWidth = 1;
        bgCtx.strokeStyle = 'rgba(0, 152, 234, 0.04)';
        bgCtx.beginPath();
        const stepY = 40;
        const stepX = 60;

        // Draw isometric-like intersecting lines
        for (let y = -h; y < h * 2; y += stepY) {
            bgCtx.moveTo(0, y); bgCtx.lineTo(w, y + w * 0.5);
            bgCtx.moveTo(0, y + w * 0.5); bgCtx.lineTo(w, y);
        }
        // Vertical lines for structure
        for (let x = 0; x < w; x += stepX) {
            bgCtx.moveTo(x, 0); bgCtx.lineTo(x, h);
        }
        bgCtx.stroke();

        // Animate and draw subtle wallet flow graph in lower left
        bgCtx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
        bgCtx.beginPath();

        for (let i = 0; i < numBgNodes; i++) {
            let n = bgNodes[i];
            n.x += n.vx; n.y += n.vy;

            // Bounce bounds
            if (n.x < 0 || n.x > w * 0.48) n.vx *= -1;
            if (n.y < h * 0.4 || n.y > h + 100) n.vy *= -1;

            // Edges
            for (let j = i + 1; j < numBgNodes; j++) {
                let n2 = bgNodes[j];
                let dx = n.x - n2.x, dy = n.y - n2.y;
                let distSqrt = dx * dx + dy * dy;
                if (distSqrt < 25000) { // approx <158 dist
                    bgCtx.moveTo(n.x, n.y);
                    bgCtx.lineTo(n2.x, n2.y);
                }
            }
        }
        bgCtx.stroke();

        // Nodes
        bgCtx.fillStyle = 'rgba(0, 152, 234, 0.15)';
        for (let i = 0; i < numBgNodes; i++) {
            let n = bgNodes[i];
            let pulse = Math.sin(Date.now() * 0.002 + i) * 1.5;
            bgCtx.beginPath();
            bgCtx.arc(n.x, n.y, Math.max(0.5, n.baseRadius + pulse), 0, Math.PI * 2);
            bgCtx.fill();
        }
    }

    // --- 2. Three.js Right Pane Matrix Visual ---
    if (typeof THREE === 'undefined') {
        console.warn('THREE.js not loaded. Hero particle matrix disabled.');
        return;
    }

    const container = document.getElementById('webgl-container');
    const scene = new THREE.Scene();

    let webGLWidth = window.innerWidth > 1024 ? w * 0.5 : w;
    let camera = new THREE.PerspectiveCamera(45, webGLWidth / h, 1, 1500);
    camera.position.z = 250;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(webGLWidth, h);
    container.appendChild(renderer.domElement);

    renderer.domElement.id = 'webgl-canvas';

    const group = new THREE.Group();
    group.position.x = 20;
    scene.add(group);

    // Generate Core Network Nodes
    const numNodes = 70;
    const nodes3D = [];
    for (let i = 0; i < numNodes; i++) {
        let r = 90 * Math.pow(Math.random(), 0.6);
        let theta = Math.random() * Math.PI * 2;
        let phi = Math.acos((Math.random() * 2) - 1);

        let x = r * Math.sin(phi) * Math.cos(theta);
        let y = r * Math.sin(phi) * Math.sin(theta);
        let z = r * Math.cos(phi);

        x = x * 1.3 + (Math.random() * 20);
        y = y * 1.1 + (x * 0.3);
        z = z * 0.6;

        nodes3D.push(new THREE.Vector3(x, y, z));
    }

    // Generate Edges
    const edges = [];
    for (let i = 0; i < numNodes; i++) {
        const dists = [];
        for (let j = 0; j < numNodes; j++) {
            if (i !== j) dists.push({ j, d: nodes3D[i].distanceToSquared(nodes3D[j]) });
        }
        dists.sort((a, b) => a.d - b.d);
        let maxCon = 3 + Math.floor(Math.random() * 4);
        for (let k = 0; k < maxCon; k++) {
            edges.push({ a: i, b: dists[k].j });
        }
    }

    const lineGeo = new THREE.BufferGeometry();
    const linePos = [];
    edges.forEach(e => {
        linePos.push(nodes3D[e.a].x, nodes3D[e.a].y, nodes3D[e.a].z);
        linePos.push(nodes3D[e.b].x, nodes3D[e.b].y, nodes3D[e.b].z);
    });
    lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(linePos, 3));
    const lineMat = new THREE.LineBasicMaterial({
        color: 0x0056D6, transparent: true, opacity: 0.1, blending: THREE.AdditiveBlending
    });
    const meshLines = new THREE.LineSegments(lineGeo, lineMat);
    group.add(meshLines);

    // 80k Particles
    const pCount = 80000;
    const pPos = new Float32Array(pCount * 3);
    const pTarget = new Float32Array(pCount * 3);
    const pParams = new Float32Array(pCount * 3);
    const pColor = new Float32Array(pCount * 3);

    const colHotCyan = new THREE.Color(0x0098EA);
    const colElecBlue = new THREE.Color(0x005EEA);
    const colViolet = new THREE.Color(0x7200EA);
    const colMagenta = new THREE.Color(0xB100EA);

    for (let i = 0; i < pCount; i++) {
        let edge = edges[Math.floor(Math.random() * edges.length)];
        let nA = nodes3D[edge.a], nB = nodes3D[edge.b];

        pPos[i * 3] = nA.x; pPos[i * 3 + 1] = nA.y; pPos[i * 3 + 2] = nA.z;
        pTarget[i * 3] = nB.x; pTarget[i * 3 + 1] = nB.y; pTarget[i * 3 + 2] = nB.z;

        pParams[i * 3] = 0.05 + Math.random() * 0.4;
        pParams[i * 3 + 1] = Math.random();
        pParams[i * 3 + 2] = 2.0 + Math.pow(Math.random(), 3) * 3.0;

        let dist = nA.length();
        let c = colHotCyan;
        let rand = Math.random();
        if (dist < 40) {
            c = rand > 0.85 ? new THREE.Color(0xffffff) : colHotCyan;
        } else if (dist < 80) {
            c = rand > 0.6 ? colHotCyan : colElecBlue;
        } else {
            c = rand > 0.7 ? colViolet : colMagenta;
        }

        pColor[i * 3] = c.r; pColor[i * 3 + 1] = c.g; pColor[i * 3 + 2] = c.b;
    }

    const pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
    pGeo.setAttribute('aTarget', new THREE.BufferAttribute(pTarget, 3));
    pGeo.setAttribute('aParams', new THREE.BufferAttribute(pParams, 3));
    pGeo.setAttribute('aColor', new THREE.BufferAttribute(pColor, 3));

    const pShaderMat = new THREE.ShaderMaterial({
        uniforms: {
            uTime: { value: 0 },
            uPixelRatio: { value: renderer.getPixelRatio() }
        },
        vertexShader: `
            uniform float uTime;
            uniform float uPixelRatio;
            attribute vec3 aTarget;
            attribute vec3 aParams;
            attribute vec3 aColor;
            varying vec3 vColor;
            varying float vAlpha;
            
            void main() {
                float speed = aParams.x;
                float offset = aParams.y;
                float pSize = aParams.z;
                
                float t = fract(uTime * speed + offset);
                float smoothT = t * t * (3.0 - 2.0 * t);
                vec3 pos = mix(position, aTarget, smoothT);
                
                vec3 mid = (position + aTarget) * 0.5;
                float dist = length(position - aTarget);
                vec3 dir = normalize(pos - mid);
                if (length(dir) < 0.001) dir = vec3(1.0, 0.0, 0.0);
                
                float arc = sin(t * 3.14159);
                pos += dir * arc * dist * 0.15;
                
                pos.y += sin(uTime * 1.5 + position.x * 0.05) * 2.0 * arc;
                pos.x += cos(uTime * 1.0 + position.y * 0.05) * 1.5 * arc;

                vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
                gl_Position = projectionMatrix * mvPosition;
                
                gl_PointSize = pSize * uPixelRatio * (200.0 / -mvPosition.z);
                
                vColor = aColor;
                vAlpha = arc;
            }
        `,
        fragmentShader: `
            varying vec3 vColor;
            varying float vAlpha;
            void main() {
                vec2 cxy = 2.0 * gl_PointCoord - 1.0;
                float dist = length(cxy);
                if(dist > 1.0) discard;
                
                float intensity = pow(1.0 - dist, 1.8);
                gl_FragColor = vec4(vColor, intensity * vAlpha * 0.8);
            }
        `,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false
    });

    const particleMesh = new THREE.Points(pGeo, pShaderMat);
    group.add(particleMesh);

    const generateGlowTexture = () => {
        const size = 256;
        const c = document.createElement('canvas');
        c.width = size; c.height = size;
        const ctx = c.getContext('2d');
        const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
        grad.addColorStop(0, 'rgba(0, 152, 234, 0.8)');
        grad.addColorStop(0.3, 'rgba(0, 86, 214, 0.2)');
        grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, size, size);
        return new THREE.CanvasTexture(c);
    };
    const glowSprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: generateGlowTexture(),
        transparent: true,
        blending: THREE.AdditiveBlending,
        opacity: 0.8
    }));
    glowSprite.scale.set(180, 180, 1);
    group.add(glowSprite);

    // --- HUD Connector Lines Logic ---
    const hudNodes = [
        nodes3D[0],
        nodes3D[Math.floor(numNodes * 0.3)],
        nodes3D[Math.floor(numNodes * 0.6)],
        nodes3D[nodes3D.length - 2]
    ];
    const hudMap = [
        { id: 'hud-1', node: hudNodes[0] },
        { id: 'hud-2', node: hudNodes[1] },
        { id: 'hud-3', node: hudNodes[2] },
        { id: 'hud-4', node: hudNodes[3] },
    ];

    const hCanvas = document.getElementById('hud-canvas');
    let hCtx = null;
    if (hCanvas) hCtx = hCanvas.getContext('2d');

    function updateHUDLines() {
        if (!hCtx) return;
        hCtx.clearRect(0, 0, w, h);
        if (window.innerWidth <= 1024) return; // Hide links on mobile

        hCtx.strokeStyle = 'rgba(0, 152, 234, 0.4)';
        hCtx.lineWidth = 1;

        hudMap.forEach(item => {
            const el = document.getElementById(item.id);
            if (!el) return;
            const rect = el.getBoundingClientRect();

            const v = item.node.clone();
            v.applyMatrix4(group.matrixWorld);
            v.project(camera);

            const screenX = (w / 2) + (v.x * 0.5 + 0.5) * (w / 2);
            const screenY = (1 - (v.y * 0.5 + 0.5)) * h;

            let startX = rect.left;
            let startY = rect.top + rect.height / 2;

            hCtx.beginPath();
            hCtx.moveTo(startX, startY);
            let midX = startX - 30;
            hCtx.lineTo(midX, startY);
            hCtx.lineTo(midX, screenY);
            hCtx.lineTo(screenX, screenY);
            hCtx.stroke();

            hCtx.beginPath();
            hCtx.arc(screenX, screenY, 2, 0, Math.PI * 2);
            hCtx.fillStyle = '#ffffff';
            hCtx.fill();

            hCtx.beginPath();
            hCtx.arc(screenX, screenY, 5, 0, Math.PI * 2);
            hCtx.strokeStyle = 'rgba(0, 152, 234, 0.8)';
            hCtx.stroke();
        });
    }

    let animationFrameId;
    const clock = new THREE.Clock();

    function animate() {
        animationFrameId = requestAnimationFrame(animate);
        drawBackgroundGraph();

        const time = clock.getElapsedTime();
        pShaderMat.uniforms.uTime.value = time;

        group.rotation.y = Math.sin(time * 0.15) * 0.15 + (Math.PI * 0.05);
        group.rotation.x = Math.cos(time * 0.2) * 0.1;

        renderer.render(scene, camera);
        updateHUDLines();
    }

    // Adjust initial sizing based on active DOM
    resizeCanvases();
    // Boot
    animate();
});
