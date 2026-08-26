/* AT89S52 P1 blink. Build:
 *   python -m niusburner build-mcs51 --source examples/at89s52_blink.c \
 *     --output out --code-size 8192 --iram-size 256
 * Flash:
 *   python -m niusburner flash at89s52 out/firmware.ihx \
 *     --confirm at89s52 --ack-data-loss --state-policy replace
 */
#include <8052.h>

void main(void)
{
    unsigned int i;
    P1 = 0x00;
    for (;;) {
        P1 = ~P1;
        for (i = 0; i < 40000U; i++) {
            ;
        }
    }
}
