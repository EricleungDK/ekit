/* Calc spec: brackets in "strings { (" and comments ) are masked */
context("Calc", {
    test("adds", {
        assertEquals(3, add(1, 2))
        assertNotEquals(5, add(1, 2))
    })
    test("keeps", {
        val msg = """sum ${add(2, 2)} "quoted" ) """
        assertEquals(4, add(2, 2))
        assertTrue(add(2, 2) > 1)
    })
})
