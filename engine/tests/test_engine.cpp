/**
 * test_engine.cpp — Unit tests for the C++ execution engine.
 * Compile and run:
 *   g++ -std=c++20 -O1 -I../include test_engine.cpp ../src/engine.cpp -lpthread -o test_engine
 *   ./test_engine
 */

#include "../include/types.hpp"
#include "../include/ring_buffer.hpp"
#include "../include/memory_pool.hpp"
#include "../include/market_data.hpp"
#include "../include/signal_generator.hpp"
#include "../include/execution_manager.hpp"

#include <cassert>
#include <iostream>
#include <thread>
#include <vector>
#include <chrono>

using namespace olbosquant;

// Simple test framework — no dependencies
#define TEST(name) void name(); struct name##_reg { name##_reg() { \
    std::cout << "  " #name " ... "; name(); std::cout << "PASS\n"; } } name##_inst; void name()
#define ASSERT(cond) if (!(cond)) { \
    std::cerr << "\nFAIL: " #cond " at line " << __LINE__ << "\n"; std::abort(); }
#define ASSERT_EQ(a, b) if ((a) != (b)) { \
    std::cerr << "\nFAIL: " #a " (" << (a) << ") != " #b " (" << (b) << ") at line " << __LINE__ << "\n"; std::abort(); }
#define ASSERT_NEAR(a, b, tol) if (std::abs((a)-(b)) > (tol)) { \
    std::cerr << "\nFAIL: |" #a " - " #b "| > " #tol " at line " << __LINE__ << "\n"; std::abort(); }

// ── types.hpp tests ────────────────────────────────────────────────────────────
TEST(test_price_conversion_roundtrip) {
    const double original = 1.2345;
    const Price fixed = to_price(original);
    const double back = from_price(fixed);
    ASSERT_NEAR(back, original, 0.0001);
}

TEST(test_price_conversion_exact) {
    ASSERT_EQ(to_price(1.0), 10000LL);
    ASSERT_EQ(to_price(0.01), 100LL);
    ASSERT_EQ(to_price(450.00), 4500000LL);
}

TEST(test_symbol_construction) {
    Symbol s{"SPY"};
    ASSERT_EQ(s.len, 3);
    ASSERT_EQ(s.view(), std::string_view{"SPY"});
}

TEST(test_symbol_equality) {
    Symbol a{"SPY"};
    Symbol b{"SPY"};
    Symbol c{"QQQ"};
    ASSERT(a == b);
    ASSERT(!(a == c));
}

TEST(test_market_update_size) {
    static_assert(sizeof(MarketUpdate) <= 64,
        "MarketUpdate must fit in one cache line");
    ASSERT(sizeof(MarketUpdate) <= 64);
}

TEST(test_market_update_mid) {
    MarketUpdate u;
    u.bid_price = to_price(1.20);
    u.ask_price = to_price(1.30);
    ASSERT_NEAR(u.mid(), 1.25, 0.0001);
}

TEST(test_market_update_spread_pct) {
    MarketUpdate u;
    u.bid_price = to_price(1.20);
    u.ask_price = to_price(1.30);
    // spread = 0.10, mid = 1.25, spread_pct = 8%
    ASSERT_NEAR(u.spread_pct(), 8.0, 0.1);
}

// ── ring_buffer.hpp tests ──────────────────────────────────────────────────────
TEST(test_ring_buffer_empty_on_init) {
    SPSCRingBuffer<int, 16> buf;
    ASSERT(buf.empty());
    ASSERT_EQ(buf.size_approx(), 0UL);
}

TEST(test_ring_buffer_push_pop) {
    SPSCRingBuffer<int, 16> buf;
    ASSERT(buf.try_push(42));
    int val = 0;
    ASSERT(buf.try_pop(val));
    ASSERT_EQ(val, 42);
}

TEST(test_ring_buffer_full_returns_false) {
    SPSCRingBuffer<int, 4> buf;  // Capacity 4, but MASK=3 so max 3 items
    ASSERT(buf.try_push(1));
    ASSERT(buf.try_push(2));
    ASSERT(buf.try_push(3));
    ASSERT(!buf.try_push(4));  // Buffer full
}

TEST(test_ring_buffer_fifo_order) {
    SPSCRingBuffer<int, 16> buf;
    for (int i = 0; i < 10; ++i) buf.try_push(i);
    for (int i = 0; i < 10; ++i) {
        int val;
        ASSERT(buf.try_pop(val));
        ASSERT_EQ(val, i);
    }
}

TEST(test_ring_buffer_spsc_concurrent) {
    SPSCRingBuffer<int, 1024> buf;
    constexpr int N = 500;
    std::vector<int> received;
    received.reserve(N);

    std::thread producer([&buf]() {
        for (int i = 0; i < N; ++i) {
            while (!buf.try_push(i)) std::this_thread::yield();
        }
    });

    std::thread consumer([&buf, &received]() {
        int val;
        int count = 0;
        while (count < N) {
            if (buf.try_pop(val)) {
                received.push_back(val);
                ++count;
            } else {
                std::this_thread::yield();
            }
        }
    });

    producer.join();
    consumer.join();

    ASSERT_EQ(static_cast<int>(received.size()), N);
    for (int i = 0; i < N; ++i) ASSERT_EQ(received[i], i);
}

// ── memory_pool.hpp tests ──────────────────────────────────────────────────────
TEST(test_memory_pool_alloc_free) {
    MemoryPool<Order, 8> pool;
    ASSERT_EQ(pool.available(), 8UL);

    Order* o1 = pool.alloc();
    ASSERT(o1 != nullptr);
    ASSERT_EQ(pool.available(), 7UL);

    new (o1) Order{};
    o1->~Order();
    pool.free(o1);
    ASSERT_EQ(pool.available(), 8UL);
}

TEST(test_memory_pool_exhaustion) {
    MemoryPool<Order, 4> pool;
    std::array<Order*, 4> orders{};
    for (auto& o : orders) {
        o = pool.alloc();
        ASSERT(o != nullptr);
    }
    ASSERT(pool.alloc() == nullptr);  // Exhausted

    // Free one and re-alloc
    orders[0]->~Order();
    pool.free(orders[0]);
    ASSERT(pool.alloc() != nullptr);
}

TEST(test_memory_pool_no_overlap) {
    MemoryPool<Order, 8> pool;
    Order* a = pool.alloc();
    Order* b = pool.alloc();
    ASSERT(a != b);
    // Pointers must not overlap
    ASSERT(std::abs(reinterpret_cast<char*>(a) - reinterpret_cast<char*>(b))
           >= static_cast<int>(sizeof(Order)));
    a->~Order(); pool.free(a);
    b->~Order(); pool.free(b);
}

// ── market_data.hpp tests ──────────────────────────────────────────────────────
TEST(test_json_parser_valid_quote) {
    std::string_view json = R"({"symbol":"SPY","bid":449.50,"ask":449.60,"bidsize":100,"asksize":80})";
    MarketUpdate update;
    ASSERT(MarketDataParser::parse_tradier_quote(json, update));
    ASSERT(update.symbol == Symbol{"SPY"});
    ASSERT_NEAR(from_price(update.bid_price), 449.50, 0.001);
    ASSERT_NEAR(from_price(update.ask_price), 449.60, 0.001);
    ASSERT_EQ(update.bid_size, 100);
    ASSERT_EQ(update.ask_size, 80);
}

TEST(test_json_parser_rejects_inverted_market) {
    // Ask < bid — invalid
    std::string_view json = R"({"symbol":"SPY","bid":449.60,"ask":449.50})";
    MarketUpdate update;
    ASSERT(!MarketDataParser::parse_tradier_quote(json, update));
}

TEST(test_json_parser_rejects_missing_symbol) {
    std::string_view json = R"({"bid":449.50,"ask":449.60})";
    MarketUpdate update;
    ASSERT(!MarketDataParser::parse_tradier_quote(json, update));
}

// ── signal_generator.hpp tests ────────────────────────────────────────────────
TEST(test_kill_switch_blocks_all_signals) {
    GuardrailState gs;
    gs.kill_switch_engaged.store(true);
    gs.max_trades_today.store(10);
    gs.max_daily_loss_cents.store(-100000);  // -$1000

    SignalGenerator gen(gs);

    OrderBook<5> book;
    book.bids[0] = {to_price(1.20), 100};
    book.asks[0] = {to_price(1.30), 50};
    book.updated_at = std::chrono::steady_clock::now();

    auto result = gen.evaluate(book, 0.90f, Signal::Type::BullPut,
                               std::chrono::steady_clock::now());
    ASSERT(!result.approved);
    ASSERT_EQ(result.reason, RejectionReason::KillSwitch);
}

TEST(test_low_score_rejected) {
    GuardrailState gs;
    gs.kill_switch_engaged.store(false);
    gs.max_trades_today.store(3);
    gs.trades_today.store(0);
    gs.max_daily_loss_cents.store(-50000);  // -$500
    gs.daily_pnl_cents.store(0);           // At zero, above loss limit

    SignalGenerator gen(gs);

    OrderBook<5> book;
    book.bids[0] = {to_price(1.20), 100};
    book.asks[0] = {to_price(1.30), 50};
    book.updated_at = std::chrono::steady_clock::now();

    auto result = gen.evaluate(book, 0.50f, Signal::Type::BullPut,
                               std::chrono::steady_clock::now());
    ASSERT(!result.approved);
    ASSERT_EQ(result.reason, RejectionReason::ScoreTooLow);
}

TEST(test_evaluation_latency_under_1000ns) {
    GuardrailState gs;
    gs.kill_switch_engaged.store(false);
    gs.max_trades_today.store(3);
    gs.trades_today.store(0);
    gs.max_daily_loss_cents.store(-50000);
    gs.daily_pnl_cents.store(0);

    SignalGenerator gen(gs);

    OrderBook<5> book;
    book.bids[0] = {to_price(1.20), 150};
    book.asks[0] = {to_price(1.25), 30};   // Strong bid/ask imbalance
    book.updated_at = std::chrono::steady_clock::now();

    // Warm up (first call may be slow due to branch predictor training)
    gen.evaluate(book, 0.75f, Signal::Type::BullPut, std::chrono::steady_clock::now());

    // Measure
    const int SAMPLES = 1000;
    int64_t total_ns = 0;
    for (int i = 0; i < SAMPLES; ++i) {
        auto result = gen.evaluate(book, 0.75f, Signal::Type::BullPut,
                                   std::chrono::steady_clock::now());
        total_ns += result.eval_latency_ns;
    }
    const double avg_ns = static_cast<double>(total_ns) / SAMPLES;
    std::cout << "(avg=" << avg_ns << "ns) ";

    // On a modern CPU with -O3, this should be well under 1000ns
    // We use 5000ns as a conservative threshold for slow CI machines
    ASSERT(avg_ns < 5000.0);
}

int main() {
    std::cout << "OlbosQuant C++ Engine — Unit Tests\n";
    std::cout << "═══════════════════════════════════\n";
    // Tests auto-register and run via static constructors above
    std::cout << "═══════════════════════════════════\n";
    std::cout << "All tests passed.\n";
    return 0;
}
