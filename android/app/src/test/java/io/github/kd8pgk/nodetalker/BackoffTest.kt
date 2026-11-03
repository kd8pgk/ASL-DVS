package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Test

class BackoffTest {

    @Test
    fun waits_double_up_to_the_limit_when_nothing_connects() {
        val b = Backoff(1000L)
        assertEquals(listOf(1000L, 2000L, 4000L, 8000L, 10000L, 10000L), List(6) { b.next(0L) })
    }

    @Test
    fun the_talk_channel_starts_at_two_seconds() {
        val b = Backoff(2000L)
        assertEquals(listOf(2000L, 4000L, 8000L, 10000L), List(4) { b.next(0L) })
    }

    @Test
    fun a_stream_that_stayed_up_resets_the_wait() {
        val b = Backoff(1000L)
        b.next(0L)
        b.next(0L)
        b.next(0L)
        assertEquals(1000L, b.next(5000L))
        assertEquals(2000L, b.next(0L))
    }

    @Test
    fun a_stream_that_dropped_at_once_keeps_backing_off() {
        val b = Backoff(1000L)
        assertEquals(1000L, b.next(0L))
        assertEquals(2000L, b.next(300L))
        assertEquals(4000L, b.next(4999L))
        assertEquals(8000L, b.next(100L))
    }

    @Test
    fun a_long_stream_resets_even_after_the_wait_reached_the_limit() {
        val b = Backoff(1000L)
        repeat(8) { b.next(0L) }
        assertEquals(1000L, b.next(60_000L))
    }
}
