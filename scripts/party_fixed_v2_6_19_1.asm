; Fixed-slot party-name experiment based on V2.6.19.
DEF GARO_TILE0 EQU $a2
DEF GARO_TILE1 EQU $a3

SECTION "runtime", ROMX[$4200], BANK[$11]
Entry:
    push hl
    push af
    ld hl, sp + 8
    ld a, [hli]
    cp $ae
    jr nz, .check_restore
    ld a, [hl]
    cp $63
    jr nz, .check_restore
    call LoadFixed
    ld a, $80
    ld [$c4f2], a
    jr .return
.check_restore:
    ld hl, sp + 8
    ld a, [hli]
    cp $b7
    jr nz, .check_roster
    ld a, [hl]
    cp $64
    jr nz, .check_roster
    call RestoreFixed
    xor a
    ld [$c4f2], a
    jr .return
.check_roster:
    ld hl, sp + 14
    ld a, [hli]
    cp $e9
    jp nz, .fallback
    ld a, [hli]
    cp $5e
    jp nz, .fallback
    ld a, [hli]
    cp $8a
    jr nz, .replay
    ld a, [hl]
    cp $49
    jr nz, .replay
    call Roster
.replay:
    pop af
    pop hl
    ld de, $0001
    ret
.fallback:
    pop af
    pop hl
    pop af
    pop af
    ld a, $10
    jp $61f0
.return:
    pop af
    pop hl
    ret

LoadFixed:
    push bc
    push de
    push hl
    ld hl, GaroPatterns
    ld de, $8a20
    ld bc, 32
    call $0521
    pop hl
    pop de
    pop bc
    ret

RestoreFixed:
    push bc
    push de
    push hl
    ld hl, NativePatterns
    ld de, $8a20
    ld bc, 32
    call $0521
    pop hl
    pop de
    pop bc
    ret

VRead:
    ldh a, [$41]
    and 2
    jr nz, VRead
    ld a, [hl]
    ret

VWrite:
    push af
.wait:
    ldh a, [$41]
    and 2
    jr nz, .wait
    pop af
    ld [hl], a
    ret

NameAddress:
    push bc
    ld a, d
    ld b, a
    add a, a
    add a, b
    ld b, a
    ldh a, [$91]
    add a, a
    add a, b
    ld b, a
    ld a, [$d2e4]
    add a, b
    add a, 2
    and 31
    ld l, a
    ld h, 0
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl
    ld bc, $9800
    add hl, bc
    ldh a, [$90]
    add a, a
    ld b, a
    ld a, [$d2e3]
    add a, b
    add a, 2
    and 31
    add a, l
    ld l, a
    pop bc
    ret

NextColumn:
    inc l
    ld a, l
    and 31
    ret nz
    ld a, l
    sub 32
    ld l, a
    ret

Roster:
    push af
    push bc
    push de
    push hl
    ldh a, [$40]
    cp $c7
    jr nz, .done
    ld a, [$c4f2]
    and a
    jr z, .returning
    cp $80
    jr nz, .done
    call LoadFixed
    jr .names
.returning:
    call LoadFixed
    ld hl, Currency0
    ld de, $8890
    ld bc, 16
    call $0521
    ld hl, Currency1
    ld de, $88c0
    ld bc, 16
    call $0521
    ld a, $80
    ld [$c4f2], a
.names:
    ld d, 0
.slot:
    ld a, d
    add a, a
    add a, d
    add a, a
    add a, a
    add a, d
    add a, $06
    ld l, a
    ld h, $d0
    ld a, [hl]
    cp 2
    jr nz, .next
    call NameAddress
    call VRead
    cp $8f
    jr nz, .failure
    call NextColumn
    call VRead
    cp $85
    jr nz, .failure
    call NextColumn
    call VRead
    cp $af
    jr nz, .failure
    call NameAddress
    ld a, GARO_TILE0
    call VWrite
    call NextColumn
    ld a, GARO_TILE1
    call VWrite
    call NextColumn
    ld a, $cd
    call VWrite
.next:
    inc d
    ld a, d
    cp 4
    jr nz, .slot
.done:
    pop hl
    pop de
    pop bc
    pop af
    ret
.failure:
    ld hl, 0
    ld de, $0c01
    ld a, $cb
    call $19e5
    jr .done

SECTION "patterns", ROMX[$4500], BANK[$11]
GaroPatterns:
    ds 32
NativePatterns:
    ds 32
Currency0:
    ds 16
Currency1:
    ds 16
