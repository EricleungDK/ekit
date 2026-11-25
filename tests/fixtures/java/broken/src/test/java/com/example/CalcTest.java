package com.example;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class CalcTest {
    @Test
    void adds() {
        int x = Calc.add(1, 2);
        assertEquals(3, x);
        assertTrue(x > 0);
    }

    @Test
    void subtracts() {
        assertEquals(1, Calc.sub(3, 2));
    }

    @Test
    void negates() {
        assertEquals(-2, Calc.neg(2));
    }

    @Test
    void addsOnes() {
        assertEquals(2, Calc.add(1, 1));
    }
}
