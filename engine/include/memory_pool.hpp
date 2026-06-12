/**
 * memory_pool.hpp — Fixed-size object pool with O(1) alloc/free.
 *
 * WHY NOT new/delete IN THE HOT PATH:
 *   The system allocator (glibc malloc) is a general-purpose allocator.
 *   It maintains free lists, handles fragmentation, and sometimes calls
 *   mmap()/brk() to request memory from the OS. Under contention from
 *   multiple threads, it uses a mutex internally. Worst-case latency:
 *   hundreds of microseconds. This is catastrophic for order submission.
 *
 * HOW THIS POOL WORKS:
 *   At startup, we allocate N objects in one contiguous slab. A free list
 *   (intrusive linked list stored IN the free slots themselves) tracks
 *   available slots. alloc() pops from the free list in ~5 instructions.
 *   free() pushes back to the free list in ~3 instructions.
 *   Both are O(1), branchless, and deterministic.
 *
 * INTRUSIVE FREE LIST:
 *   Each free slot stores the index of the next free slot in its first bytes.
 *   No separate metadata array — the storage itself IS the free list.
 *   This maximizes cache utilization: when you allocate, the data you write
 *   is already in cache from the free-list traversal.
 *
 * THREAD SAFETY:
 *   NOT thread-safe by design. One pool per thread (thread-local storage)
 *   eliminates all contention. If you need cross-thread sharing, use
 *   the SPSCRingBuffer to return objects back to their origin thread.
 *
 * USAGE:
 *   // At startup (once, before trading):
 *   MemoryPool<Order, 1024> order_pool;
 *
 *   // In hot path (O(1), no heap):
 *   Order* order = order_pool.alloc();
 *   if (!order) { /* pool exhausted — handle */ }
 *   new (order) Order{...};  // placement new — no allocation, just construction
 *
 *   // After order completes:
 *   order->~Order();          // explicit destructor
 *   order_pool.free(order);   // returns slot to pool
 */

#pragma once

#include <array>
#include <cstdint>
#include <cstddef>
#include <cassert>
#include <type_traits>

namespace olbosquant {

template<typename T, std::size_t N>
class MemoryPool {
    static_assert(N > 0, "Pool size must be positive");
    static_assert(sizeof(T) >= sizeof(std::size_t),
        "Object must be at least as large as a pointer index for intrusive free list");

public:
    MemoryPool() noexcept {
        // Build the intrusive free list at construction time
        // Each slot points to the next slot. Last slot points to SENTINEL.
        for (std::size_t i = 0; i < N - 1; ++i) {
            *reinterpret_cast<std::size_t*>(&storage_[i]) = i + 1;
        }
        *reinterpret_cast<std::size_t*>(&storage_[N - 1]) = SENTINEL;
        free_head_ = 0;
        available_ = N;
    }

    // Non-copyable — owns fixed memory
    MemoryPool(const MemoryPool&)            = delete;
    MemoryPool& operator=(const MemoryPool&) = delete;

    /**
     * alloc — Get a raw storage slot. O(1), no system calls.
     * Returns nullptr if pool is exhausted.
     * Caller must use placement new to construct the object.
     */
    [[nodiscard]] T* alloc() noexcept {
        if (free_head_ == SENTINEL) [[unlikely]] {
            return nullptr;  // Pool exhausted
        }
        const std::size_t idx = free_head_;
        // Read next free index from the slot itself (intrusive list)
        free_head_ = *reinterpret_cast<std::size_t*>(&storage_[idx]);
        --available_;
        return reinterpret_cast<T*>(&storage_[idx]);
    }

    /**
     * free — Return a slot to the pool. O(1).
     * Caller must have already called the destructor.
     */
    void free(T* ptr) noexcept {
        assert(ptr != nullptr);
        // Verify pointer is within our pool (debug builds only)
        assert(ptr >= reinterpret_cast<T*>(&storage_[0]));
        assert(ptr <  reinterpret_cast<T*>(&storage_[N]));

        const std::size_t idx = ptr - reinterpret_cast<T*>(&storage_[0]);
        *reinterpret_cast<std::size_t*>(&storage_[idx]) = free_head_;
        free_head_ = idx;
        ++available_;
    }

    [[nodiscard]] std::size_t available() const noexcept { return available_; }
    [[nodiscard]] std::size_t used()      const noexcept { return N - available_; }
    [[nodiscard]] static constexpr std::size_t capacity() noexcept { return N; }

private:
    static constexpr std::size_t SENTINEL = std::numeric_limits<std::size_t>::max();

    // Aligned storage: same alignment as T, N slots, no construction yet
    // alignas(T) ensures proper alignment for placement new
    alignas(T) std::array<
        std::byte[sizeof(T)],
        N
    > storage_;

    std::size_t free_head_{SENTINEL};
    std::size_t available_{0};
};

}  // namespace olbosquant
