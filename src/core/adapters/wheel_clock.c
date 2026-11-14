/* GPL-3.0. Adapt only the wheel's private tap/hold clock to milliseconds.
   The game's HID sampling numbers remain untouched after the callback. */
typedef unsigned long long u64;
extern u64 hmb_get_tick(void);
extern u64 hmb_get_tick_frequency(void);
extern void hmb_original_raw(u64 *state, unsigned count);
extern volatile unsigned hmb_hold_ms;

void hmb_wheel_clock(u64 *state, unsigned count) {
    if (!state || !count || count > 64) return;
    const u64 saved_sample = state[0];
    const u64 frequency = hmb_get_tick_frequency();
    if (frequency) {
        const u64 tick = hmb_get_tick();
        u64 hold = hmb_hold_ms;
        if (hold < 40 || hold > 500) hold = 100;
        const u64 rate = (192000 + hold / 2) / hold;
        state[0] = (tick / frequency) * rate + ((tick % frequency) * rate) / frequency;
    }
    hmb_original_raw(state, count);
    state[0] = saved_sample;
}
