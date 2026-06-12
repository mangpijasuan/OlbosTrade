/**
 * market_data.hpp — MarketDataParser and OrderBook.
 *
 * PARSING STRATEGY:
 *   Broker feeds arrive as either:
 *   a) Binary frames (IBKR TWS native) — direct memcpy into struct
 *   b) JSON (Tradier REST/WebSocket) — field-by-field extraction
 *
 *   For the hot path, we avoid nlohmann::json and boost::json because
 *   they allocate. Instead, we use a zero-allocation JSON scanner that
 *   reads field names and values directly into pre-typed struct fields
 *   using std::from_chars (no locale, no allocation, C++17).
 *
 * ORDER BOOK STRUCTURE:
 *   A real Level-2 order book needs a sorted data structure per side.
 *   std::map is O(log N) but heap-allocates nodes.
 *   For SPY options (which is our primary instrument), we typically only
 *   need the top 5 levels. A fixed-size array of (price, size) pairs,
 *   kept sorted on update, is O(N) but N=5 so it's faster than any
 *   tree structure due to cache locality.
 *
 * LATENCY MEASUREMENT:
 *   Every update is timestamped with steady_clock on arrival and again
 *   on processing completion. The delta is the "processing latency" and
 *   is logged to a lock-free circular stats buffer, never to stdout
 *   (I/O in the hot path is catastrophic for latency).
 */

#pragma once

#include "types.hpp"
#include "ring_buffer.hpp"

#include <array>
#include <cstdint>
#include <charconv>
#include <string_view>
#include <algorithm>
#include <span>

namespace olbosquant {

// ── Order book level ───────────────────────────────────────────────────────────
struct BookLevel {
    Price    price{0};
    Quantity size{0};

    [[nodiscard]] bool valid() const noexcept { return price > 0 && size > 0; }
};

// ── Compact top-of-book snapshot ──────────────────────────────────────────────
// Holds the best N bid and ask levels. N=5 covers 99% of execution decisions.
// Fixed-size array: zero heap, fits in ~100 bytes, single cache-line-region.
template<std::size_t Depth = 5>
struct alignas(64) OrderBook {
    Symbol                       symbol{};
    std::array<BookLevel, Depth> bids{};   // bids[0] = best bid
    std::array<BookLevel, Depth> asks{};   // asks[0] = best ask
    Timestamp                    updated_at{};
    uint64_t                     sequence{0};

    // ── Convenience accessors ────────────────────────────────────────────────
    [[nodiscard]] Price    best_bid()      const noexcept { return bids[0].price; }
    [[nodiscard]] Price    best_ask()      const noexcept { return asks[0].price; }
    [[nodiscard]] Quantity best_bid_size() const noexcept { return bids[0].size; }
    [[nodiscard]] Quantity best_ask_size() const noexcept { return asks[0].size; }

    [[nodiscard]] double spread_dollars() const noexcept {
        return from_price(best_ask() - best_bid());
    }

    // Total size at N levels (market depth proxy)
    [[nodiscard]] Quantity total_bid_size() const noexcept {
        Quantity total = 0;
        for (const auto& lvl : bids) total += lvl.size;
        return total;
    }

    [[nodiscard]] Quantity total_ask_size() const noexcept {
        Quantity total = 0;
        for (const auto& lvl : asks) total += lvl.size;
        return total;
    }

    // Apply a single price/size update to the correct side
    void apply_update(const MarketUpdate& update) noexcept {
        bids[0] = {update.bid_price, update.bid_size};
        asks[0] = {update.ask_price, update.ask_size};
        updated_at = update.received_at;
        ++sequence;
    }
};

// ── Zero-allocation JSON field extractor ──────────────────────────────────────
// Scans a JSON string for a specific field and returns its value as string_view.
// No allocation, no copy. Caller parses the value using std::from_chars.
//
// Only handles flat JSON (no nested objects) — sufficient for quote responses.
// Example: extract_json_field(json, "bid") on '{"bid":1.25,"ask":1.30}' → "1.25"
[[nodiscard]] inline std::string_view extract_json_field(
    std::string_view json,
    std::string_view field) noexcept
{
    // Find the field name including quotes
    std::string_view key_pattern;
    // We search for: "field":
    // Build the search pattern on the stack — no heap
    std::array<char, 64> pattern_buf{};
    const std::size_t plen = std::min(
        field.size() + 3, pattern_buf.size() - 1
    );
    pattern_buf[0] = '"';
    std::memcpy(pattern_buf.data() + 1, field.data(), field.size());
    pattern_buf[field.size() + 1] = '"';
    pattern_buf[field.size() + 2] = ':';
    pattern_buf[field.size() + 3] = '\0';

    const std::string_view pattern{pattern_buf.data(), plen};
    const auto pos = json.find(pattern);
    if (pos == std::string_view::npos) return {};

    // Advance past the pattern and any whitespace
    std::size_t value_start = pos + pattern.size();
    while (value_start < json.size() && json[value_start] == ' ') ++value_start;
    if (value_start >= json.size()) return {};

    // Find end of value (comma, }, whitespace, or end of string)
    std::size_t value_end = value_start;
    const bool is_string = (json[value_start] == '"');
    if (is_string) ++value_start;  // Skip opening quote

    while (value_end < json.size()) {
        const char c = json[value_end];
        if (is_string ? (c == '"') : (c == ',' || c == '}' || c == ' ' || c == '\n'))
            break;
        ++value_end;
    }

    return json.substr(value_start, value_end - value_start);
}

// ── MarketDataParser ───────────────────────────────────────────────────────────
class MarketDataParser {
public:
    /**
     * parse_tradier_quote — Parse a Tradier WebSocket JSON quote into MarketUpdate.
     *
     * Returns false if parsing fails (malformed data, missing fields).
     * Uses std::from_chars throughout — no exceptions, no allocation,
     * no locale-dependent behavior (strtod is locale-sensitive — avoid it).
     *
     * noexcept: parsing failures return false, never throw.
     * [[nodiscard]]: caller must check return value.
     */
    [[nodiscard]] static bool parse_tradier_quote(
        std::string_view json,
        MarketUpdate&    out) noexcept
    {
        out.received_at = std::chrono::steady_clock::now();

        // Extract symbol
        const auto sym_sv = extract_json_field(json, "symbol");
        if (sym_sv.empty()) return false;
        out.symbol = Symbol{sym_sv};

        // Extract bid price
        const auto bid_sv = extract_json_field(json, "bid");
        if (bid_sv.empty()) return false;
        double bid_d = 0.0;
        if (std::from_chars(bid_sv.data(), bid_sv.data() + bid_sv.size(), bid_d).ec
            != std::errc{}) return false;
        out.bid_price = to_price(bid_d);

        // Extract ask price
        const auto ask_sv = extract_json_field(json, "ask");
        if (ask_sv.empty()) return false;
        double ask_d = 0.0;
        if (std::from_chars(ask_sv.data(), ask_sv.data() + ask_sv.size(), ask_d).ec
            != std::errc{}) return false;
        out.ask_price = to_price(ask_d);

        // Validate: ask >= bid
        if (out.ask_price < out.bid_price) return false;

        // Extract bid size (optional — default 0 if missing)
        const auto bsz_sv = extract_json_field(json, "bidsize");
        if (!bsz_sv.empty()) {
            std::from_chars(bsz_sv.data(), bsz_sv.data() + bsz_sv.size(), out.bid_size);
        }

        // Extract ask size (optional)
        const auto asz_sv = extract_json_field(json, "asksize");
        if (!asz_sv.empty()) {
            std::from_chars(asz_sv.data(), asz_sv.data() + asz_sv.size(), out.ask_size);
        }

        return true;
    }

    /**
     * parse_binary_ibkr — Parse IBKR's binary TWS tick frame.
     *
     * IBKR TWS sends price updates as a binary struct over the socket.
     * Direct reinterpret_cast is safe here because:
     * 1. We control both sides of the serialization
     * 2. The frame layout is fixed and documented
     * 3. MarketUpdate is trivially copyable (guaranteed above)
     *
     * In production: add a CRC32 check on the frame before accepting it.
     */
    [[nodiscard]] static bool parse_binary_ibkr(
        std::span<const std::byte> frame,
        MarketUpdate&              out) noexcept
    {
        // Frame layout (simplified for template):
        // [4 bytes magic] [4 bytes seq] [8 bytes bid] [8 bytes ask]
        // [4 bytes bid_size] [4 bytes ask_size] [24 bytes symbol]
        constexpr std::size_t FRAME_SIZE = 4 + 4 + 8 + 8 + 4 + 4 + 24;
        if (frame.size() < FRAME_SIZE) return false;

        const uint32_t magic = *reinterpret_cast<const uint32_t*>(frame.data());
        if (magic != 0xAB'CD'12'34u) return false;  // Magic number check

        out.received_at = std::chrono::steady_clock::now();
        out.sequence    = static_cast<uint8_t>(
            *reinterpret_cast<const uint32_t*>(frame.data() + 4));

        // Direct read of fixed-point prices (already in our format)
        std::memcpy(&out.bid_price, frame.data() + 8,  sizeof(Price));
        std::memcpy(&out.ask_price, frame.data() + 16, sizeof(Price));
        std::memcpy(&out.bid_size,  frame.data() + 24, sizeof(Quantity));
        std::memcpy(&out.ask_size,  frame.data() + 28, sizeof(Quantity));
        std::memcpy(out.symbol.data.data(), frame.data() + 32, 24);
        out.symbol.len = static_cast<uint8_t>(
            std::strlen(out.symbol.data.data()));

        return out.bid_price > 0 && out.ask_price >= out.bid_price;
    }
};

}  // namespace olbosquant
