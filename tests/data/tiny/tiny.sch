EESchema Schematic File Version 4
EELAYER 30 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 1 2
Title "tiny test board"
Date "2020-07-16"
Rev "0.1"
Comp "kicad-revive"
Comment1 ""
Comment2 ""
Comment3 ""
Comment4 ""
$EndDescr
$Comp
L Device:R R1
U 1 1 5E0C0001
P 3000 2000
F 0 "R1" H 3070 2046 50  0000 L CNN
F 1 "10k" H 3070 1955 50  0000 L CNN
F 2 "Resistor_SMD:R_0402_1005Metric" V 2930 2000 50  0001 C CNN
F 3 "~" H 3000 2000 50  0001 C CNN
	1    3000 2000
	1    0    0    -1
$EndComp
$Comp
L Device:C C1
U 1 1 5E0C0002
P 4000 2000
F 0 "C1" V 3748 2000 50  0000 C CNN
F 1 "100n" V 3839 2000 50  0000 C CNN
F 2 "Capacitor_SMD:C_0402_1005Metric" H 4038 1850 50  0001 C CNN
F 3 "~" H 4000 2000 50  0001 C CNN
	1    4000 2000
	0    -1   -1   0
$EndComp
$Comp
L power:GND #PWR0101
U 1 1 5E0C0003
P 3000 2500
F 0 "#PWR0101" H 3000 2250 50  0001 C CNN
F 1 "GND" H 3005 2327 50  0000 C CNN
F 2 "" H 3000 2500 50  0001 C CNN
F 3 "" H 3000 2500 50  0001 C CNN
	1    3000 2500
	1    0    0    1
$EndComp
Wire Wire Line
	3000 1850 3000 1500
Wire Wire Line
	3000 2150 3000 2500
Wire Wire Line
	3850 2000 3000 2000
Wire Notes Line
	2500 1200 5000 1200
Connection ~ 3000 2000
NoConn ~ 4150 2000
Text Label 3000 1500 0    50   ~ 0
VOUT
Text GLabel 2400 2000 0    50   Input ~ 0
VIN
Text GLabel 5200 2000 2    50   Output ~ 0
VSENSE
Text Notes 2500 1150 0    79   ~ 0
Power Supply Section
$Sheet
S 2500 3500 1500 800
U 5E0C0100
F0 "sub" 50
F1 "sub.sch" 50
F2 "ENABLE" I L 2500 3700 50
$EndSheet
$EndSCHEMATC
