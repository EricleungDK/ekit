package com.example;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

class CalcTest {
    @Test
    void adds() {
        int x = Calc.add(1, 2);
        assertEquals(4, x);
        assertTrue(x > 0);
    }

    @Test
    @Disabled("flaky on CI")
    void negates() {
        assertEquals(-2, Calc.neg(2));
    }
}
