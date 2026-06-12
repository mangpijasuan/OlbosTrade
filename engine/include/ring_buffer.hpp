/**
 * ring_buffer.hpp — Lock-free Single-Producer Single-Consumer (SPSC) ring buffer.
 *
 * WHY SPSC OVER A MUTEX-PROTECTED QUEUE:
 *   A mutex causes a context switch when contended — the OS suspends your thread,
 *   saves its state, schedules another thread, then eventually restores yours.
 *   On Linux, a context switch costs ~3-10 microseconds. A single options order
 *   submission round-trip might be 5ms total — we cannot afford to throw away
 *   10us on a context switch just to pass a market update between threads.
 *
 *   The SPSC ring buffer uses std::atomic with memory_order_acquire/release
 *   instead. This inserts a hardware memory fence — the CPU's store buffer
 *   is flushed — but no OS involvement, no thread suspension.
 *   Cost: ~5-20 nanoseconds instead of 3-10 microseconds. 1000x faster.
 *
 * WHY SPSC SPECIFICALLY (not MPMC):
 *   We have exactly two threads: market data thread (producer) and execution
 *   thread (consumer). SPSC can be implemented with just TWO atomics (head and
 *   tail) and zero CAS (compare-and-swap) instructions. MPMC queues require
 *   CAS loops which can suffer from contention under high throughput.
 *
 * CACHE-LINE PADDING:
 *   head_ and tail_ are accessed by different threads. Without padding, they
 *   could share a cache line — when one thread writes to head_, the CPU must
 *   invalidate the cache line on the other core (false sharing). This causes
 *   ~200ns stalls. The padding ensures each atomic lives on its own cache line.
 *
 * POWER-OF-TWO CAPACITY:
 *   Wrapping an index is normally: index = (index + 1) % capacity
 *   For power-of-two capacity: index = (index + 1) & MASK  (bitwise AND)
 *   The CPU executes AND in 1 cycle vs 20-90 cycles for division/modulo.
 *
 * USAGE:
 *   // Market data thread (producer):
 *   MarketUpdate update = parse_feed(raw_bytes);
 *   if (!queue.try_push(update)) { /* handle backpressure */ }
 *
 *   // Execution thread (consumer):
 *   MarketUpdate update;
 *   if (queue.try_pop(update)) { process(update); }
 */

#pragma once

#include <atomic>
#include <array>
#include <optional>
#include <cstddef>
#include <type_traits>

namespace olbosquant {

template<typename T, std::size_t Capacity>
requires (std::is_trivially_copyable_v<T>)       // C++20 concept constraint
      && ((Capacity & (Capacity - 1)) == 0)       // Must be power of 2
      && (Capacity >= 2)
class SPSCRingBuffer {
public:
    static constexpr std::size_t MASK = Capacity - 1;

    SPSCRingBuffer() noexcept = default;

    // Non-copyable, non-movable — owns the buffer
    SPSCRingBuffer(const SPSCRingBuffer&)            = delete;
    SPSCRingBuffer& operator=(const SPSCRingBuffer&) = delete;

    /**
     * try_push — Producer side. Called from market data thread ONLY.
     *
     * memory_order_relaxed on head_ load: the producer owns head_, so it
     * doesn't need a synchronization fence to read its own variable.
     *
     * memory_order_release on tail_ store: ensures all writes to buffer_[pos]
     * are visible to the consumer before the tail index update is visible.
     * This is the "release" in the acquire-release protocol.
     *
     * Returns false if the buffer is full — caller must handle backpressure.
     * Never blocks. Never allocates. noexcept guaranteed.
     */
    [[nodiscard]] bool try_push(const T& item) noexcept {
        const std::size_t head = head_.load(std::memory_order_relaxed);
        const std::size_t next = (head + 1) & MASK;

        // Buffer is full if next write position equals consumer's read position
        if (next == tail_.load(std::memory_order_acquire)) {
            return false;  // Full — do NOT overwrite unconsumed data
        }

        buffer_[head] = item;  // Write to pre-allocated slot

        // Release fence: makes buffer_[head] visible to consumer
        head_.store(next, std::memory_order_release);
        return true;
    }

    /**
     * try_pop — Consumer side. Called from execution thread ONLY.
     *
     * memory_order_acquire on head_ load: synchronizes with the producer's
     * memory_order_release store. This is the "acquire" in acquire-release.
     * Guarantees we see the complete buffer_[pos] write before we read it.
     *
     * memory_order_release on tail_ store: tells producer the slot is free.
     */
    [[nodiscard]] bool try_pop(T& item) noexcept {
        const std::size_t tail = tail_.load(std::memory_order_relaxed);

        // Empty if tail equals head
        if (tail == head_.load(std::memory_order_acquire)) {
            return false;
        }

        item = buffer_[tail];  // Copy from pre-allocated slot

        // Release: tells producer this slot is now available
        tail_.store((tail + 1) & MASK, std::memory_order_release);
        return true;
    }

    /**
     * size — approximate size. May be stale by the time caller reads it.
     * Use only for monitoring, never for correctness decisions.
     */
    [[nodiscard]] std::size_t size_approx() const noexcept {
        const std::size_t h = head_.load(std::memory_order_relaxed);
        const std::size_t t = tail_.load(std::memory_order_relaxed);
        return (h - t + Capacity) & MASK;
    }

    [[nodiscard]] bool empty() const noexcept {
        return head_.load(std::memory_order_acquire) ==
               tail_.load(std::memory_order_acquire);
    }

    [[nodiscard]] static constexpr std::size_t capacity() noexcept {
        return Capacity;
    }

private:
    // ── Cache-line separation ─────────────────────────────────────────────────
    // head_ written by producer, read by both. Pad to its own 64-byte cache line
    // so producer writes don't cause false sharing on consumer's cache line.
    alignas(64) std::atomic<std::size_t> head_{0};
    char pad0_[64 - sizeof(std::atomic<std::size_t>)]{};

    // tail_ written by consumer, read by both.
    alignas(64) std::atomic<std::size_t> tail_{0};
    char pad1_[64 - sizeof(std::atomic<std::size_t>)]{};

    // The actual data buffer — pre-allocated, zero heap involvement
    alignas(64) std::array<T, Capacity> buffer_{};
};

}  // namespace olbosquant
