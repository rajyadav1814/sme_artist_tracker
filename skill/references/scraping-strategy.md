# Scraping Strategy Reference

## Sony Music Latin Website Structure

### URL Patterns
- Main roster: `https://www.sonymusiclatin.com/artists/`
- Paginated: `https://www.sonymusiclatin.com/artist/page/{N}/` (note: `/artist/` not `/artists/`)
- Individual artist: `https://www.sonymusiclatin.com/{artist-slug}/`

### Known Access Issues
The site may return 403 on direct fetch. Fallback strategies:

1. **Google cache**: Search `cache:sonymusiclatin.com/artists/`
2. **Web search extraction**: Search `site:sonymusiclatin.com/artist` to discover all artist pages
3. **Wikipedia roster**: `https://en.wikipedia.org/wiki/Sony_Music_Latin` maintains a current artist list
4. **Social search**: For each artist, search `"{artist name}" sony music latin official` to find verified profiles

### HTML Structure (when accessible)
Artist cards typically contain:
- `<div class="artist-card">` or similar grid item
- `<img>` with headshot (usually square, ~300×300)
- `<h2>` or `<h3>` with artist name
- `<a>` links to social profiles (usually icon links in a row)
- `<a>` link to individual artist page on SML

### Social Link Selectors
Social icons are typically `<a>` tags with:
- Class names containing platform name (e.g., `social-instagram`)
- `href` matching platform URL patterns
- `<i>` or `<svg>` icons with platform-identifying classes

---

## Platform-Specific Scraping Notes

### Instagram
- Profile pages require authentication for most data
- **Best approach**: Search `"{artist}" instagram followers site:socialblade.com` or
  `"{artist}" instagram followers 2026`
- Look for verified badge mention in results

### YouTube
- Channel pages are publicly accessible
- Subscriber count visible at `youtube.com/@{handle}`
- Use web_fetch on the channel page; look for subscriber count in page text
- Video view counts available on individual video pages

### TikTok
- Profile pages may load dynamically (JS-rendered)
- **Best approach**: Search `"{artist}" tiktok followers` for reported counts
- Social Blade TikTok pages are a reliable backup

### X / Twitter
- Profile pages accessible but may require JS rendering
- **Best approach**: Search `"{artist}" twitter followers` or check Social Blade
- Recent tweets visible in search results

### Spotify
- Artist profile pages are publicly accessible
- `open.spotify.com/artist/{id}` shows monthly listeners in the page
- web_fetch the profile page and extract the monthly listener count
- Top tracks and latest releases visible on the page

### Apple Music
- Artist pages accessible at `music.apple.com/us/artist/{slug}/{id}`
- Shows top songs and latest releases
- Less structured for scraping; web search is often more reliable

### Facebook
- Page like/follower counts visible on public pages
- `facebook.com/{handle}` — look for "X people like this" text
- Increasingly less relevant for younger artists

---

## Rate Limiting & Politeness

- Space requests at least 2 seconds apart for the same domain
- Rotate between platforms (don't hit Instagram 50 times in a row)
- Prefer search aggregators when available to reduce direct platform hits
- Cache results aggressively — social metrics don't change minute-to-minute
- If rate limited, back off and use cached/search data with staleness note
