EESchema Schematic File Version 4
EELAYER 30 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 2 2
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
L Device:R R?
U 1 1 5E0C0201
P 2000 2000
AR Path="/5E0C0201" Ref="R?"  Part="1" 
AR Path="/5E0C0100/5E0C0201" Ref="R2"  Part="1" 
F 0 "R2" H 2070 2046 50  0000 L CNN
F 1 "1k" H 2070 1955 50  0000 L CNN
F 2 "Resistor_SMD:R_0402_1005Metric" V 1930 2000 50  0001 C CNN
F 3 "~" H 2000 2000 50  0001 C CNN
	1    2000 2000
	1    0    0    -1
$EndComp
Text GLabel 1600 2000 0    50   Input ~ 0
VIN
Wire Wire Line
	1600 2000 2000 1850
$EndSCHEMATC
