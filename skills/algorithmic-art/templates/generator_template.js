// Algorithmic Art Generator Template
// Replace placeholders with your own values

let seed;
let params = {
  seed: null,           // Set to specific value for reproducibility, null for random
  scale: 0.01,          // Noise scale
  complexity: 5,        // Detail level (1-10)
  colorMode: 'rainbow', // 'rainbow', 'monochrome', 'complementary', 'custom'
  baseHue: 180,         // Base hue for color schemes (0-360)
  animate: false        // Set true for animation
};

function setup() {
  createCanvas(800, 800);
  seed = params.seed || floor(random(999999));
  randomSeed(seed);
  noiseSeed(seed);
  colorMode(HSB, 360, 100, 100, 100);

  if (!params.animate) {
    noLoop();
    generateArt();
  }

  console.log('Seed:', seed);
}

function draw() {
  if (params.animate) {
    generateArt();
  }
}

function generateArt() {
  background(20);

  // === YOUR ALGORITHM HERE ===
  // Example: Flow field
  let cols = width / 20;
  let rows = height / 20;

  for (let x = 0; x < cols; x++) {
    for (let y = 0; y < rows; y++) {
      let px = x * 20 + 10;
      let py = y * 20 + 10;

      let n = noise(x * params.scale * 10, y * params.scale * 10);
      let angle = n * TWO_PI * params.complexity;

      push();
      translate(px, py);
      rotate(angle);

      let hue = (params.baseHue + n * 120) % 360;
      stroke(hue, 80, 90, 80);
      strokeWeight(2);
      line(0, 0, 15, 0);
      pop();
    }
  }
  // === END ALGORITHM ===
}

// Keyboard controls
function keyPressed() {
  if (key === 's' || key === 'S') {
    saveCanvas(`art_${seed}`, 'png');
    console.log('Saved as art_' + seed + '.png');
  }
  if (key === 'r' || key === 'R') {
    seed = floor(random(999999));
    randomSeed(seed);
    noiseSeed(seed);
    console.log('New seed:', seed);
    if (!params.animate) redraw();
  }
  if (key === ' ') {
    params.animate = !params.animate;
    if (params.animate) loop();
    else noLoop();
  }
}

// Mouse interaction
function mousePressed() {
  params.baseHue = map(mouseX, 0, width, 0, 360);
  if (!params.animate) redraw();
}
