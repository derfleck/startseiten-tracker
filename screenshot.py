import asyncio
from playwright.async_api import async_playwright
from datetime import datetime, timedelta
import os
import glob
import shutil
from jinja2 import Template
from pytz import timezone
import logging
from colorama import Fore, Style, init
import aiohttp
import json

# Initialize colorama for colored output
init()

# Configure logging with colors
class ColoredFormatter(logging.Formatter):
    FORMATS = {
        logging.INFO: Fore.GREEN + "%(message)s" + Style.RESET_ALL,
        logging.ERROR: Fore.RED + "%(message)s" + Style.RESET_ALL,
        logging.WARNING: Fore.YELLOW + "%(message)s" + Style.RESET_ALL,
        logging.DEBUG: Style.DIM + "%(message)s" + Style.RESET_ALL
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter())
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Semaphore to limit concurrent browser instances
CONCURRENT_BROWSERS = 3
browser_semaphore = asyncio.Semaphore(CONCURRENT_BROWSERS)

TIMELINE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Startseiten-Radar</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/swiper/swiper-bundle.min.css">
    <style>
        body { 
            margin: 0;
            font-family: Arial, sans-serif;
            background: #f5f5f5;
        }
        .timeline-controls {
            position: sticky;
            top: 0;
            background: white;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            z-index: 100;
        }
        .device-toggle {
            display: flex;
            gap: 10px;
            margin: 10px 0;
        }
        .device-toggle button {
            flex: 1;
            padding: 8px;
            border: 1px solid #ddd;
            background: white;
            cursor: pointer;
        }
        .device-toggle button.active {
            background: #007bff;
            color: white;
            border-color: #0056b3;
        }
        
        /* Desktop Layout */
        @media (min-width: 768px) {
            .screenshots-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                gap: 20px;
                padding: 20px;
            }
            .site-card {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 15px;
                background: white;
            }
            .mobile-view {
                display: none;
            }
        }
        
        /* Mobile Layout */
        @media (max-width: 767px) {
            .screenshots-grid {
                display: none;
            }
            .mobile-view {
                display: block;
                height: calc(100vh - 150px);
            }
            .swiper {
                width: 100%;
                height: 100%;
            }
            .swiper-slide {
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 15px;
            }
            .site-info {
                text-align: center;
                margin-bottom: 15px;
            }
        }
        
        .device-views {
            display: grid;
            gap: 15px;
        }
        .device-view img {
            width: 100%;
            height: auto;
            border: 1px solid #eee;
            border-radius: 4px;
            transition: transform 0.2s;
            cursor: pointer;
        }
        .device-view img:hover {
            transform: scale(1.02);
        }
        
        /* Modal styles */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
            padding: 20px;
            box-sizing: border-box;
            justify-content: center;
            align-items: center;
        }
        
        .modal-container {
            position: relative;
            max-width: 90%;
            max-height: 90vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        
        .modal-content {
            max-width: 100%;
            max-height: 90vh;
            width: auto;
            height: auto;
            object-fit: contain;
            display: block;
        }
        
        /* Timeline slider styles */
        .device-view img {
            transition: opacity 0.3s ease-in-out;
        }
        
        .device-view img.loading {
            opacity: 0.5;
        }
        
        .timeline-slider {
            width: 100%;
            padding: 10px 0;
        }
        
        .slider-container {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin: 15px 0;
        }
        
        .slider-controls {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .navigation-buttons {
            display: flex;
            gap: 5px;
        }
        
        .nav-button {
            padding: 8px 12px;
            border: none;
            background: #007bff;
            color: white;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        
        .nav-button:hover {
            background: #0056b3;
        }
        
        .current-timestamp {
            font-size: 1.1em;
            font-weight: bold;
            min-width: 200px;
        }
        
        input[type="range"] {
            flex-grow: 1;
            height: 10px;
            -webkit-appearance: none;
            background: #ddd;
            border-radius: 5px;
            outline: none;
        }
        
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 20px;
            height: 20px;
            background: #007bff;
            border-radius: 50%;
            cursor: pointer;
        }
        
        .play-button {
            padding: 8px 15px;
            border: none;
            background: #007bff;
            color: white;
            border-radius: 4px;
            cursor: pointer;
        }
        
        .play-button:hover {
            background: #0056b3;
        }
        
        input[type="range"].form-range {
            height: 1.5rem;
            padding: 0;
            background: transparent;
        }
        
        input[type="range"].form-range::-webkit-slider-thumb {
            margin-top: -6px;
            width: 1rem;
            height: 1rem;
            background-color: #0d6efd;
            border: 0;
            border-radius: 1rem;
            transition: background-color .15s ease-in-out,border-color .15s ease-in-out,box-shadow .15s ease-in-out;
            appearance: none;
        }
        
        input[type="range"].form-range::-webkit-slider-runnable-track {
            width: 100%;
            height: 0.5rem;
            color: transparent;
            cursor: pointer;
            background-color: #dee2e6;
            border-color: transparent;
            border-radius: 1rem;
        }
        
        .site-title {
            margin: 0;
            padding: 0;
        }
        
        .site-title a {
            color: #333;
            text-decoration: none;
            font-weight: bold;
        }
        
        .site-title a:hover {
            color: #0d6efd;
        }
        
        .error-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,0,0,0.1);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #721c24;
            background-color: #f8d7da;
            padding: 10px;
            text-align: center;
            font-size: 0.9em;
        }
        
        .device-view {
            position: relative;
        }
    </style>
</head>
<body>
    <div class="timeline-controls">
        <h1>Startseiten</h1>
        <div class="slider-container">
            <div class="slider-controls">
                <button class="play-button" id="playButton">> Play</button>
                <div class="navigation-buttons">
                    <button class="nav-button" id="prevButton"><</button>
                    <button class="nav-button" id="nextButton">></button>
                </div>
                <span class="current-timestamp" id="currentTimestamp"></span>
            </div>
            <input type="range" class="form-range timeline-slider" id="timelineSlider" min="0" max="{{ timestamps|length - 1 }}" value="0">
        </div>
        <div class="device-toggle">
            <button class="active" data-device="desktop">Desktop</button>
            <button data-device="mobile">Mobile</button>
        </div>
        <p class="timestamp">Letztes Update: {{ generated_at }}</p>
    </div>
    
    <!-- Desktop Layout -->
    <div class="screenshots-grid">
        {% for site in sites %}
        <div class="site-card">
            <h3 class="site-title"><a href="{{ site.url }}" target="_blank">{{ site.name }}</a></h3>
            <div class="device-view" data-current-device="desktop">
                <img src="archive/{{ timestamps[0] }}/{{ site.name }}_desktop.jpeg" 
                    class="screenshot-img"
                    data-site="{{ site.name }}"
                    data-device="desktop"
                    onclick="openModal(this)">
            </div>
        </div>
        {% endfor %}
    </div>

    <!-- Mobile Layout -->
    <div class="mobile-view">
        <div class="swiper">
            <div class="swiper-wrapper">
                {% for site in sites %}
                <div class="swiper-slide">
                    <div class="site-info">
                        <h3 class="site-title"><a href="{{ site.url }}" target="_blank">{{ site.name }}</a></h3>
                    </div>
                    <div class="device-view" data-current-device="desktop">
                        <img src="archive/{{ timestamps[0] }}/{{ site.name }}_desktop.jpeg" 
                            class="screenshot-img"
                            data-site="{{ site.name }}"
                            data-device="desktop"
                            onclick="openModal(this)">
                    </div>
                </div>
                {% endfor %}
            </div>
            <div class="swiper-pagination"></div>
        </div>
    </div>

    <!-- Modal -->
    <div id="imageModal" class="modal">
        <span class="modal-close" onclick="closeModal()">&times;</span>
        <div class="modal-container">
            <img class="modal-content" id="modalImage">
        </div>
    </div>

    <script src="https://unpkg.com/swiper/swiper-bundle.min.js"></script>
    <script>
        // Initialize Swiper
        const swiper = new Swiper('.swiper', {
            pagination: {
                el: '.swiper-pagination',
            },
            spaceBetween: 30,
            keyboard: true,
        });

        const modal = document.getElementById('imageModal');
        const modalImg = document.getElementById('modalImage');

        function openModal(img) {
            modal.style.display = "flex";
            modalImg.src = img.src;
        }

        function closeModal() {
            modal.style.display = "none";
        }

        modal.onclick = function(event) {
            if (event.target === modal) {
                closeModal();
            }
        }

        // Initialize timestamps array (reversed for chronological order)
        const timestamps = {{ timestamps|tojson }}.reverse();
        let currentIndex = timestamps.length - 1; // Start with most recent
        let isPlaying = false;
        let playInterval;
        let isTransitioning = false;
        
        // Format timestamp for display (YYYYMMDD_HHMM to DD.MM.YYYY HH:MM)
        function formatTimestamp(timestamp) {
            const year = timestamp.slice(0, 4);
            const month = timestamp.slice(4, 6);
            const day = timestamp.slice(6, 8);
            const hour = timestamp.slice(9, 11);
            const minute = timestamp.slice(11, 13);
            return `${day}.${month}.${year} ${hour}:${minute}`;
        }
        
        // Add new function to check if image exists
        async function imageExists(url) {
            return new Promise((resolve) => {
                const img = new Image();
                img.onload = () => resolve(true);
                img.onerror = () => resolve(false);
                img.src = url;
            });
        }
        
        // Modified updateScreenshots function
        async function updateScreenshots(timestamp) {
            if (isTransitioning) return;
            isTransitioning = true;
            
            const images = document.querySelectorAll('.screenshot-img');
            images.forEach(img => img.classList.add('loading'));
            
            const device = document.querySelector('.device-toggle button.active').dataset.device;
            
            for (const img of images) {
                const newSrc = `archive/${timestamp}/${img.dataset.site}_${device}.jpeg`;
                const exists = await imageExists(newSrc);
                
                const deviceView = img.closest('.device-view');
                const existingError = deviceView.querySelector('.error-overlay');
                if (existingError) {
                    existingError.remove();
                }
                
                if (exists) {
                    img.src = newSrc;
                } else {
                    // Keep previous image if it exists, otherwise show error
                    if (!img.src || img.src.endsWith('undefined')) {
                        const errorDiv = document.createElement('div');
                        errorDiv.className = 'error-overlay';
                        errorDiv.textContent = 'Screenshot nicht verfügbar';
                        deviceView.appendChild(errorDiv);
                    }
                }
                img.classList.remove('loading');
            }
            
            document.getElementById('currentTimestamp').textContent = formatTimestamp(timestamp);
            isTransitioning = false;
        }
        
        // Initialize slider
        const slider = document.getElementById('timelineSlider');
        const playButton = document.getElementById('playButton');
        const prevButton = document.getElementById('prevButton');
        const nextButton = document.getElementById('nextButton');
        
        slider.max = timestamps.length - 1;
        slider.value = currentIndex;
        
        // Navigation functions
        function goToNext() {
            if (currentIndex < timestamps.length - 1) {
                currentIndex++;
                slider.value = currentIndex;
                updateScreenshots(timestamps[currentIndex]);
            }
        }
        
        function goToPrev() {
            if (currentIndex > 0) {
                currentIndex--;
                slider.value = currentIndex;
                updateScreenshots(timestamps[currentIndex]);
            }
        }
        
        // Event listeners
        slider.addEventListener('input', (e) => {
            currentIndex = parseInt(e.target.value);
            updateScreenshots(timestamps[currentIndex]);
        });
        
        prevButton.addEventListener('click', goToPrev);
        nextButton.addEventListener('click', goToNext);
        
        // Play/Pause functionality with smoother transitions
        function togglePlay() {
            isPlaying = !isPlaying;
            playButton.textContent = isPlaying ? '⏸ Pause' : '▶ Play';
            
            if (isPlaying) {
                playInterval = setInterval(() => {
                    if (!isTransitioning) {
                        if (currentIndex === timestamps.length - 1) {
                            currentIndex = 0;
                        } else {
                            currentIndex++;
                        }
                        slider.value = currentIndex;
                        updateScreenshots(timestamps[currentIndex]);
                    }
                }, 2000);
            } else {
                clearInterval(playInterval);
            }
        }
        
        playButton.addEventListener('click', togglePlay);
        
        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeModal();
            } else if (e.key === 'ArrowLeft') {
                goToPrev();
            } else if (e.key === 'ArrowRight') {
                goToNext();
            } else if (e.key === ' ') {
                e.preventDefault();
                togglePlay();
            }
        });
        
        // Touch gestures for mobile
        let touchStartX = 0;
        document.addEventListener('touchstart', (e) => {
            touchStartX = e.touches[0].clientX;
        });
        
        document.addEventListener('touchend', (e) => {
            const touchEndX = e.changedTouches[0].clientX;
            const diff = touchEndX - touchStartX;
            
            if (Math.abs(diff) > 50) { // Minimum swipe distance
                if (diff > 0) {
                    goToPrev();
                } else {
                    goToNext();
                }
            }
        });
        
        // Initialize with most recent timestamp
        updateScreenshots(timestamps[currentIndex]);
        
        // Device toggle (modified)
        document.querySelectorAll('.device-toggle button').forEach(button => {
            button.addEventListener('click', () => {
                const device = button.dataset.device;
                document.querySelectorAll('.device-toggle button').forEach(b => b.classList.remove('active'));
                button.classList.add('active');
                updateScreenshots(timestamps[currentIndex]);
            });
        });

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeModal();
            }
        });
    </script>
</body>
</html>
"""

async def take_screenshot(config: dict, device_type: str = 'desktop'):
    async with browser_semaphore:
        async with async_playwright() as p:
            try:
                # Device configurations with more CI-friendly settings
                devices = {
                    'desktop': {
                        'viewport': {'width': 1920, 'height': 1080},
                        'user_agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        'device_scale_factor': 1,
                    },
                    'mobile': {
                        **p.devices['iPhone 13'],
                        'device_scale_factor': 1,
                    }
                }
                
                # Launch browser with additional arguments for CI environment
                browser = await p.chromium.launch(
                    args=[
                        '--disable-dev-shm-usage',  # Handles limited memory in CI
                        '--no-sandbox',  # Required for running in containers
                        '--font-render-hinting=none',  # Helps with font consistency
                        '--disable-gpu',  # Better stability in CI
                    ]
                )
                
                context = await browser.new_context(
                    **devices[device_type],
                    bypass_csp=True,  # Helps with loading fonts
                    locale='de-AT'  # Ensure consistent locale
                )
                
                page = await context.new_page()
                
                # Set longer timeouts for CI environment
                page.set_default_timeout(30000)
                
                output_dir = config.get('output_dir', '.')
                output_path = f"{output_dir}/{config['name']}_{device_type}.jpeg"
                
                try:
                    await page.goto(
                        config['url'],
                        wait_until='networkidle',  # Wait for network to be idle
                        timeout=30000
                    )
                    
                    # Wait longer in CI environment
                    await page.wait_for_timeout(5000)
                    
                    # Handle consent screens and popups
                    try:
                        if config.get('frame_selector'):
                            frame = page.frame_locator(config['frame_selector'])
                            await frame.locator(config['button_selector']).click(timeout=5000)
                            logger.info(f"Clicked consent button in frame for {config['name']}")
                        else:
                            await page.locator(config['button_selector']).click(timeout=5000)
                            logger.info(f"Clicked consent button for {config['name']}")
                        
                        # Wait longer for consent screen to disappear
                        await page.wait_for_timeout(2000)
                        
                        # Additional check for consent screen visibility
                        try:
                            is_visible = await page.locator(config['button_selector']).is_visible()
                            if is_visible:
                                logger.warning(f"Consent button still visible for {config['name']} after clicking")
                                # Try clicking again
                                await page.locator(config['button_selector']).click(timeout=2000)
                        except Exception:
                            pass
                            
                    except Exception as e:
                        logger.warning(f"Consent handling error for {config['name']}: {str(e)}")
                    
                    # Wait for any animations to complete
                    await page.wait_for_timeout(3000)
                    
                    # Take screenshot with adjusted quality settings
                    await page.screenshot(
                        path=output_path,
                        type='jpeg',
                        quality=50,  # Slightly higher quality
                        full_page=False
                    )
                    
                    logger.info(f"Screenshot captured for {config['name']} ({device_type})")
                    
                except Exception as e:
                    logger.error(f"Error processing {config['name']} ({device_type}): {str(e)}")
                    try:
                        await page.screenshot(path=output_path, type='jpeg', quality=35)
                        logger.info(f"Fallback screenshot captured for {config['name']} ({device_type})")
                    except Exception as screenshot_error:
                        logger.error(f"Failed to capture fallback screenshot for {config['name']}: {str(screenshot_error)}")
                        
            finally:
                await browser.close()

# Modify take_timestamped_screenshots to handle errors
async def take_timestamped_screenshots(sites):
    """Take timestamped screenshots for a list of sites."""
    tz = timezone('Europe/Vienna')
    timestamp = datetime.now(tz).strftime('%Y%m%d_%H%M')
    screenshots_dir = f'archive/{timestamp}'
    os.makedirs(screenshots_dir, exist_ok=True)
    
    async def safe_screenshot(site, device):
        try:
            site.update({'output_dir': screenshots_dir})
            await take_screenshot(site, device)
            return True
        except Exception as e:
            logger.error(f"Failed to capture {device} screenshot for {site['name']}: {str(e)}")
            return False
    
    tasks = []
    for site in sites:
        for device in ['desktop', 'mobile']:
            tasks.append(safe_screenshot(site, device))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"Completed screenshot batch: {sum(1 for r in results if r)} successful, {sum(1 for r in results if not r)} failed")
    
    return timestamp

def cleanup_old_screenshots():
    """Remove screenshots older than 48 hours"""
    cutoff = datetime.now() - timedelta(hours=48)
    for dir_path in glob.glob('archive/*'):
        dir_time = datetime.strptime(os.path.basename(dir_path), '%Y%m%d_%H%M')
        if dir_time < cutoff:
            shutil.rmtree(dir_path)

def generate_timeline_report(sites):
    # Get last 48h of timestamps (192 entries for 15min intervals)
    timestamps = sorted(glob.glob('archive/*'), reverse=True)[:192]
    timestamps = [os.path.basename(t) for t in timestamps]
    
    if not timestamps:
        print("No archives found")
        return
    
    template = Template(TIMELINE_HTML)
    # Specify the timezone
    tz = timezone('Europe/Vienna')

    html_content = template.render(
        timestamps=timestamps,
        sites=sites,
        generated_at=datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S %Z')
    )
    
    with open('index.html', 'w') as f:
        f.write(html_content)

async def fetch_sites_config():
    """Fetch sites configuration from GitHub Gist or local file"""
    try:
        # First try to load local config
        with open('sites.json', 'r') as f:
            config = json.load(f)
            
        if config.get('gist_id'):
            # If gist_id is configured, try to fetch from GitHub
            async with aiohttp.ClientSession() as session:
                url = f"https://api.github.com/gists/{config['gist_id']}"
                async with session.get(url) as response:
                    if response.status == 200:
                        gist = await response.json()
                        # Get the first file content from the gist
                        content = next(iter(gist['files'].values()))['content']
                        return json.loads(content)['sites']
                    else:
                        logger.warning("Could not fetch from Gist, using local configuration")
                        return config['sites']
        return config['sites']
    except Exception as e:
        logger.error(f"Error fetching configuration: {str(e)}")
        # If all else fails, load the bundled configuration
        with open('sites.json', 'r') as f:
            return json.load(f)['sites']

async def main():
    # Fetch site configurations
    sites = await fetch_sites_config()
    logger.info(f"Loaded configuration for {len(sites)} sites")
    
    # Take new screenshots
    timestamp = await take_timestamped_screenshots(sites)
    print(f"Screenshots captured at: {timestamp}")
    
    # Generate updated report
    generate_timeline_report(sites)
    print("Timeline report updated")
    
    cleanup_old_screenshots()
    print("Old screenshots cleaned up")

# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
